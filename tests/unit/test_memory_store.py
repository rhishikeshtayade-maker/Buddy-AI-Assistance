"""Unit tests for SQLite MemoryStore persistence layer."""

from __future__ import annotations

import time
import unittest

from app.core.exceptions import MemoryStorageError
from app.memory.models import MemoryRecord, MemorySensitivity, MemorySource, MemoryStatus, MemoryType
from app.memory.store import SqliteMemoryStore


class TestMemoryStore(unittest.TestCase):
    """Test SQLite storage, parameterized queries, soft-deletion, search, and limits."""

    def setUp(self) -> None:
        # In-memory SQLite store for clean unit tests
        self.store = SqliteMemoryStore(db_path=":memory:", max_records=20)

    def tearDown(self) -> None:
        self.store.close()

    def test_save_and_get_record(self) -> None:
        rec = MemoryRecord(
            content="User prefers Python 3.13",
            memory_type=MemoryType.SEMANTIC,
            source=MemorySource.USER_EXPLICIT,
            tags=["python"],
        )
        self.store.save(rec)

        fetched = self.store.get(rec.memory_id)
        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertEqual(fetched.content, "User prefers Python 3.13")
        self.assertEqual(fetched.tags, ["python"])
        self.assertEqual(fetched.version, 1)

    def test_update_record_increments_version(self) -> None:
        rec = MemoryRecord(
            content="Initial preference",
            memory_type=MemoryType.PROFILE,
        )
        self.store.save(rec)

        rec.content = "Updated preference"
        self.store.update(rec)

        updated = self.store.get(rec.memory_id)
        assert updated is not None
        self.assertEqual(updated.content, "Updated preference")
        self.assertEqual(updated.version, 2)

    def test_soft_delete_prevents_retrieval(self) -> None:
        rec = MemoryRecord(content="Temporary fact to delete")
        self.store.save(rec)

        self.assertTrue(self.store.delete(rec.memory_id))
        self.assertIsNone(self.store.get(rec.memory_id))

    def test_keyword_search_and_active_filtering(self) -> None:
        rec1 = MemoryRecord(content="Favorite editor is VS Code", tags=["editor"])
        rec2 = MemoryRecord(content="Prefers Chrome browser", tags=["browser"])
        rec3 = MemoryRecord(content="Uses VS Code for Python", tags=["editor", "python"])
        self.store.save(rec1)
        self.store.save(rec2)
        self.store.save(rec3)

        results = self.store.search(query="editor")
        self.assertEqual(len(results), 2)
        contents = [r.content for r in results]
        self.assertIn("Favorite editor is VS Code", contents)
        self.assertIn("Uses VS Code for Python", contents)

    def test_expiration_marks_stale_records(self) -> None:
        now = time.time()
        stale_rec = MemoryRecord(
            content="Expired session context",
            memory_type=MemoryType.SESSION,
            expires_at=now - 10.0,
        )
        fresh_rec = MemoryRecord(
            content="Active session context",
            memory_type=MemoryType.SESSION,
            expires_at=now + 100.0,
        )
        self.store.save(stale_rec)
        self.store.save(fresh_rec)

        expired_count = self.store.expire_records(current_time=now)
        self.assertEqual(expired_count, 1)

        # Stale record is excluded from active search
        active_results = self.store.search("session", active_only=True)
        self.assertEqual(len(active_results), 1)
        self.assertEqual(active_results[0].content, "Active session context")

    def test_sql_injection_defense(self) -> None:
        malicious_input = "'; DROP TABLE memory_records; --"
        rec = MemoryRecord(content=malicious_input)
        self.store.save(rec)

        fetched = self.store.get(rec.memory_id)
        assert fetched is not None
        self.assertEqual(fetched.content, malicious_input)

        # Confirm table still exists and functions properly
        self.store.search(malicious_input)
        self.assertEqual(self.store.count(), 1)

    def test_max_records_limit_enforced(self) -> None:
        small_store = SqliteMemoryStore(db_path=":memory:", max_records=3)
        try:
            for i in range(3):
                small_store.save(MemoryRecord(content=f"Fact {i}"))

            with self.assertRaises(MemoryStorageError):
                small_store.save(MemoryRecord(content="Fact 4 exceeding limit"))
        finally:
            small_store.close()


if __name__ == "__main__":
    unittest.main()
