"""BUDDY Persistent SQLite Memory Store.

Implements the MemoryStore storage abstraction using SQLite with:
1. Strict parameterized queries (zero SQL injection vulnerabilities).
2. Schema migrations and versioning.
3. WAL journal mode for concurrent read/write resilience on Windows.
4. Bounded database size and record counts to prevent memory expansion DOS.
5. Integration with MemoryEncryptor for encrypting sensitive content at rest.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from app.core.exceptions import MemoryStorageError
from app.memory.encryption import MemoryEncryptor, NoOpMemoryEncryptor
from app.memory.models import MemoryRecord, MemorySensitivity, MemorySource, MemoryStatus, MemoryType

logger = logging.getLogger("buddy.memory.store")

CURRENT_SCHEMA_VERSION = 1


class MemoryStore(ABC):
    """Storage contract for persisting, querying, and updating memory records."""

    @abstractmethod
    def save(self, record: MemoryRecord) -> None:
        """Persist a new memory record."""
        ...

    @abstractmethod
    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        """Retrieve a memory record by ID."""
        ...

    @abstractmethod
    def update(self, record: MemoryRecord) -> None:
        """Update an existing memory record."""
        ...

    @abstractmethod
    def delete(self, memory_id: str) -> bool:
        """Mark or remove a memory record."""
        ...

    @abstractmethod
    def search(
        self,
        query: str,
        memory_type: Optional[MemoryType] = None,
        limit: int = 10,
        active_only: bool = True,
    ) -> List[MemoryRecord]:
        """Search records matching keyword query."""
        ...

    @abstractmethod
    def list_records(
        self,
        memory_type: Optional[MemoryType] = None,
        status: Optional[MemoryStatus] = None,
        limit: int = 100,
    ) -> List[MemoryRecord]:
        """List memory records filtered by type and status."""
        ...

    @abstractmethod
    def clear(self, memory_type: Optional[MemoryType] = None) -> int:
        """Clear all or category-specific records. Returns count of removed records."""
        ...

    @abstractmethod
    def expire_records(self, current_time: Optional[float] = None) -> int:
        """Mark all records whose expires_at is before current_time as EXPIRED."""
        ...

    @abstractmethod
    def count(self, memory_type: Optional[MemoryType] = None, active_only: bool = True) -> int:
        """Return total record count."""
        ...

    @abstractmethod
    def get_database_size_bytes(self) -> int:
        """Return physical database file size in bytes."""
        ...

    @abstractmethod
    def close(self) -> None:
        """Close database connection."""
        ...


class SqliteMemoryStore(MemoryStore):
    """SQLite implementation with parameterized queries, schema versioning, and encryption."""

    def __init__(
        self,
        db_path: Path | str = "data/memory.db",
        encryptor: Optional[MemoryEncryptor] = None,
        max_size_mb: int = 50,
        max_records: int = 1000,
    ) -> None:
        self._db_path = Path(db_path)
        self._encryptor = encryptor or NoOpMemoryEncryptor()
        self._max_size_bytes = max_size_mb * 1024 * 1024
        self._max_records = max_records
        self._lock = threading.RLock()

        # Ensure parent directory exists if using on-disk database
        if str(self._db_path) != ":memory:":
            self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            timeout=30.0,
        )
        self._conn.row_factory = sqlite3.Row

        with self._lock:
            # Enable WAL mode for file-based DBs
            if str(self._db_path) != ":memory:":
                try:
                    self._conn.execute("PRAGMA journal_mode=WAL;")
                except sqlite3.Error as e:
                    logger.warning("Could not set journal_mode=WAL: %s", e)
            self._conn.execute("PRAGMA foreign_keys=ON;")
            self._initialize_schema()

    def _initialize_schema(self) -> None:
        """Apply schema migrations and create required tables and indexes."""
        cursor = self._conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at REAL NOT NULL
            );
            """
        )
        self._conn.commit()

        cursor.execute("SELECT MAX(version) FROM schema_migrations;")
        row = cursor.fetchone()
        current_v = row[0] if row and row[0] is not None else 0

        if current_v < 1:
            self._apply_migration_v1(cursor)
            cursor.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?);",
                (1, time.time()),
            )
            self._conn.commit()
            logger.info("Applied memory store schema migration v1.")

    def _apply_migration_v1(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_records (
                memory_id TEXT PRIMARY KEY,
                memory_type TEXT NOT NULL,
                source TEXT NOT NULL,
                sensitivity TEXT NOT NULL,
                content TEXT NOT NULL,
                confidence REAL NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_accessed_at REAL NOT NULL,
                expires_at REAL,
                user_confirmed INTEGER NOT NULL DEFAULT 0,
                tags TEXT NOT NULL DEFAULT '[]',
                metadata TEXT NOT NULL DEFAULT '{}',
                version INTEGER NOT NULL DEFAULT 1
            );
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mem_type ON memory_records(memory_type);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mem_status ON memory_records(status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mem_expires ON memory_records(expires_at);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mem_source ON memory_records(source);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mem_created ON memory_records(created_at);")

    def _check_storage_limits(self) -> None:
        """Assert database size and total record counts do not exceed configured ceilings."""
        if str(self._db_path) != ":memory:" and self._db_path.exists():
            size = self._db_path.stat().st_size
            if size > self._max_size_bytes:
                raise MemoryStorageError(
                    f"Memory database size ({size / (1024*1024):.1f}MB) exceeds "
                    f"maximum allowed limit ({self._max_size_bytes / (1024*1024):.1f}MB)."
                )

        cursor = self._conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM memory_records WHERE status != 'deleted';")
        count = cursor.fetchone()[0]
        if count >= self._max_records:
            raise MemoryStorageError(
                f"Memory record count ({count}) reached maximum configured capacity ({self._max_records})."
            )

    def save(self, record: MemoryRecord) -> None:
        with self._lock:
            self._check_storage_limits()

            # Encrypt content before storing
            encrypted_content = self._encryptor.encrypt(record.content)

            tags_json = json.dumps(record.tags)
            meta_json = json.dumps(record.metadata)

            try:
                cursor = self._conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO memory_records (
                        memory_id, memory_type, source, sensitivity, content,
                        confidence, status, created_at, updated_at, last_accessed_at,
                        expires_at, user_confirmed, tags, metadata, version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        record.memory_id,
                        record.memory_type.value,
                        record.source.value,
                        record.sensitivity.value,
                        encrypted_content,
                        record.confidence,
                        record.status.value,
                        record.created_at,
                        record.updated_at,
                        record.last_accessed_at,
                        record.expires_at,
                        1 if record.user_confirmed else 0,
                        tags_json,
                        meta_json,
                        record.version,
                    ),
                )
                self._conn.commit()
            except sqlite3.Error as e:
                raise MemoryStorageError(f"Failed to save memory record '{record.memory_id}': {e}") from e

    def _row_to_record(self, row: sqlite3.Row) -> MemoryRecord:
        raw_content = row["content"]
        decrypted_content = self._encryptor.decrypt(raw_content)

        return MemoryRecord(
            memory_id=row["memory_id"],
            memory_type=MemoryType(row["memory_type"]),
            source=MemorySource(row["source"]),
            sensitivity=MemorySensitivity(row["sensitivity"]),
            content=decrypted_content,
            confidence=row["confidence"],
            status=MemoryStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_accessed_at=row["last_accessed_at"],
            expires_at=row["expires_at"],
            user_confirmed=bool(row["user_confirmed"]),
            tags=json.loads(row["tags"]),
            metadata=json.loads(row["metadata"]),
            version=row["version"],
        )

    def get(self, memory_id: str) -> Optional[MemoryRecord]:
        with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute(
                    "SELECT * FROM memory_records WHERE memory_id = ? AND status != 'deleted';",
                    (memory_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None

                # Update last accessed timestamp
                now = time.time()
                cursor.execute(
                    "UPDATE memory_records SET last_accessed_at = ? WHERE memory_id = ?;",
                    (now, memory_id),
                )
                self._conn.commit()

                rec = self._row_to_record(row)
                rec.last_accessed_at = now
                return rec
            except sqlite3.Error as e:
                raise MemoryStorageError(f"Failed to retrieve memory record '{memory_id}': {e}") from e

    def update(self, record: MemoryRecord) -> None:
        with self._lock:
            encrypted_content = self._encryptor.encrypt(record.content)
            now = time.time()

            try:
                cursor = self._conn.cursor()
                cursor.execute(
                    """
                    UPDATE memory_records SET
                        memory_type = ?,
                        source = ?,
                        sensitivity = ?,
                        content = ?,
                        confidence = ?,
                        status = ?,
                        updated_at = ?,
                        last_accessed_at = ?,
                        expires_at = ?,
                        user_confirmed = ?,
                        tags = ?,
                        metadata = ?,
                        version = version + 1
                    WHERE memory_id = ?;
                    """,
                    (
                        record.memory_type.value,
                        record.source.value,
                        record.sensitivity.value,
                        encrypted_content,
                        record.confidence,
                        record.status.value,
                        now,
                        now,
                        record.expires_at,
                        1 if record.user_confirmed else 0,
                        json.dumps(record.tags),
                        json.dumps(record.metadata),
                        record.memory_id,
                    ),
                )
                self._conn.commit()
            except sqlite3.Error as e:
                raise MemoryStorageError(f"Failed to update memory record '{record.memory_id}': {e}") from e

    def delete(self, memory_id: str) -> bool:
        with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute(
                    "UPDATE memory_records SET status = 'deleted', updated_at = ? WHERE memory_id = ? AND status != 'deleted';",
                    (time.time(), memory_id),
                )
                self._conn.commit()
                return cursor.rowcount > 0
            except sqlite3.Error as e:
                raise MemoryStorageError(f"Failed to delete memory record '{memory_id}': {e}") from e

    def search(
        self,
        query: str,
        memory_type: Optional[MemoryType] = None,
        limit: int = 10,
        active_only: bool = True,
    ) -> List[MemoryRecord]:
        with self._lock:
            # Clean and bound query length to prevent DOS
            cleaned_query = query.strip()[:200]
            if not cleaned_query:
                return []

            # Retrieve active records and decrypt for keyword matching
            params: List[Any] = []
            clauses = ["status != 'deleted'"]

            if active_only:
                clauses.append("status = 'active'")
                clauses.append("(expires_at IS NULL OR expires_at > ?)")
                params.append(time.time())

            if memory_type is not None:
                clauses.append("memory_type = ?")
                params.append(memory_type.value)

            where_sql = " AND ".join(clauses)
            sql = f"SELECT * FROM memory_records WHERE {where_sql} ORDER BY user_confirmed DESC, confidence DESC, updated_at DESC;"

            try:
                cursor = self._conn.cursor()
                cursor.execute(sql, params)
                rows = cursor.fetchall()
            except sqlite3.Error as e:
                raise MemoryStorageError(f"Failed to execute memory search: {e}") from e

            # Perform keyword match against decrypted content and tags
            matched: List[MemoryRecord] = []
            raw_terms = re.findall(r"\b\w+\b", cleaned_query.lower())
            query_terms = [t for t in raw_terms if len(t) >= 2]

            for row in rows:
                rec = self._row_to_record(row)
                content_lower = rec.content.lower()
                tags_lower = [t.lower() for t in rec.tags]

                if not query_terms:
                    matched.append(rec)
                elif any(term in content_lower for term in query_terms) or any(term in tags_lower for term in query_terms):
                    matched.append(rec)

                if len(matched) >= limit:
                    break

            return matched

    def list_records(
        self,
        memory_type: Optional[MemoryType] = None,
        status: Optional[MemoryStatus] = None,
        limit: int = 100,
    ) -> List[MemoryRecord]:
        with self._lock:
            params: List[Any] = []
            clauses: List[str] = []

            if status is not None:
                clauses.append("status = ?")
                params.append(status.value)
            else:
                clauses.append("status != 'deleted'")

            if memory_type is not None:
                clauses.append("memory_type = ?")
                params.append(memory_type.value)

            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            sql = f"SELECT * FROM memory_records {where_sql} ORDER BY created_at DESC LIMIT ?;"
            params.append(limit)

            try:
                cursor = self._conn.cursor()
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                return [self._row_to_record(r) for r in rows]
            except sqlite3.Error as e:
                raise MemoryStorageError(f"Failed to list memory records: {e}") from e

    def clear(self, memory_type: Optional[MemoryType] = None) -> int:
        with self._lock:
            try:
                cursor = self._conn.cursor()
                if memory_type:
                    cursor.execute(
                        "DELETE FROM memory_records WHERE memory_type = ?;",
                        (memory_type.value,),
                    )
                else:
                    cursor.execute("DELETE FROM memory_records;")
                self._conn.commit()
                return cursor.rowcount
            except sqlite3.Error as e:
                raise MemoryStorageError(f"Failed to clear memory records: {e}") from e

    def expire_records(self, current_time: Optional[float] = None) -> int:
        with self._lock:
            now = current_time if current_time is not None else time.time()
            try:
                cursor = self._conn.cursor()
                cursor.execute(
                    """
                    UPDATE memory_records
                    SET status = 'expired', updated_at = ?
                    WHERE status = 'active' AND expires_at IS NOT NULL AND expires_at <= ?;
                    """,
                    (now, now),
                )
                self._conn.commit()
                return cursor.rowcount
            except sqlite3.Error as e:
                raise MemoryStorageError(f"Failed to expire stale memory records: {e}") from e

    def count(self, memory_type: Optional[MemoryType] = None, active_only: bool = True) -> int:
        with self._lock:
            params: List[Any] = []
            clauses = ["status != 'deleted'"]
            if active_only:
                clauses.append("status = 'active'")
                clauses.append("(expires_at IS NULL OR expires_at > ?)")
                params.append(time.time())

            if memory_type is not None:
                clauses.append("memory_type = ?")
                params.append(memory_type.value)

            where_sql = " AND ".join(clauses)
            cursor = self._conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM memory_records WHERE {where_sql};", params)
            return cursor.fetchone()[0]

    def get_database_size_bytes(self) -> int:
        if str(self._db_path) == ":memory:":
            return 0
        if self._db_path.exists():
            return self._db_path.stat().st_size
        return 0

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass
