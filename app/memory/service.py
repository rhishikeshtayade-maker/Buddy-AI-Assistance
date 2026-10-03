"""BUDDY Long-Term Memory Service.

Orchestrates candidate validation, policy enforcement, conflict resolution,
bounded retrieval, lifecycle expiration, and audit/event logging.
Enforces non-negotiable rule: Memory is contextual data, NEVER security authority.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import BuddyConfig
from app.core.events import EventBus
from app.core.exceptions import MemoryPolicyViolationError, MemoryStorageError
from app.memory.events import (
    MemoryClearedEvent,
    MemoryConflictDetectedEvent,
    MemoryCreatedEvent,
    MemoryDeletedEvent,
    MemoryExpiredEvent,
    MemoryRejectedEvent,
    MemoryRetrievedEvent,
    MemoryUpdatedEvent,
)
from app.memory.models import (
    MemoryCandidate,
    MemoryRecord,
    MemorySensitivity,
    MemorySource,
    MemoryStatus,
    MemoryType,
)
from app.memory.policy import MemoryPolicy, PolicyDecisionType
from app.memory.store import MemoryStore

logger = logging.getLogger("buddy.memory.service")


class MemoryService:
    """Core memory business logic layer enforcing safety, lifecycle, and bounded retrieval."""

    def __init__(
        self,
        store: MemoryStore,
        policy: Optional[MemoryPolicy] = None,
        event_bus: Optional[EventBus] = None,
        config: Optional[BuddyConfig] = None,
    ) -> None:
        self._store = store
        self._config = config or BuddyConfig()
        self._policy = policy or MemoryPolicy(self._config)
        self._event_bus = event_bus

    async def _publish(self, event: Any) -> None:
        if self._event_bus:
            try:
                await self._event_bus.publish(event)
            except Exception as e:
                logger.warning("Failed to publish memory event: %s", e)

    async def record_memory(
        self,
        content: str,
        memory_type: MemoryType = MemoryType.SEMANTIC,
        source: MemorySource = MemorySource.USER_EXPLICIT,
        confidence: float = 1.0,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> MemoryRecord:
        """Evaluate, resolve conflicts, and store an approved memory candidate."""
        candidate = MemoryCandidate(
            content=content,
            memory_type=memory_type,
            source=source,
            confidence=confidence,
            tags=tags or [],
            metadata=metadata or {},
        )

        # 1. Policy Evaluation
        decision = self._policy.evaluate_candidate(candidate)
        if not decision.is_allowed:
            await self._publish(
                MemoryRejectedEvent(
                    reason=decision.reason,
                    source=source.value,
                )
            )
            raise MemoryPolicyViolationError(
                f"Memory policy rejected content: {decision.reason}",
                details={"decision": decision.decision.value},
            )

        now = time.time()
        expires_at = (now + decision.ttl_seconds) if decision.ttl_seconds else None
        user_confirmed = (source == MemorySource.USER_EXPLICIT)

        # 2. Conflict Detection & Resolution
        existing_conflicts = self._detect_conflicts(content, memory_type)
        superseded_id: Optional[str] = None

        if existing_conflicts:
            older_rec = existing_conflicts[0]
            # If new record is explicit user preference, supersede older preference
            if source in (MemorySource.USER_EXPLICIT, MemorySource.USER_CONFIRMED):
                superseded_id = older_rec.memory_id
                older_rec.status = MemoryStatus.ARCHIVED
                self._store.update(older_rec)
                logger.info(
                    "Memory conflict resolved: archived older record '%s' in favor of newer explicit preference.",
                    older_rec.memory_id,
                )
                await self._publish(
                    MemoryConflictDetectedEvent(
                        existing_memory_id=older_rec.memory_id,
                        resolution="archived_older_preference",
                    )
                )

        # 3. Create & Store Record
        record = MemoryRecord(
            memory_type=decision.suggested_type,
            source=source,
            sensitivity=decision.suggested_sensitivity,
            content=content.strip(),
            confidence=confidence,
            status=MemoryStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            last_accessed_at=now,
            expires_at=expires_at,
            user_confirmed=user_confirmed,
            tags=tags or [],
            metadata=metadata or {},
        )

        self._store.save(record)

        await self._publish(
            MemoryCreatedEvent(
                memory_id=record.memory_id,
                memory_type=record.memory_type.value,
                source=record.source.value,
                sensitivity=record.sensitivity.value,
            )
        )

        return record

    def _detect_conflicts(self, content: str, memory_type: MemoryType) -> List[MemoryRecord]:
        """Detect existing active memories that may contradict the new content."""
        words = set(content.lower().split())
        # Check domain-specific conflict triggers (e.g. browser, editor, language)
        preference_domains = [
            ("browser", ["chrome", "firefox", "edge", "brave", "safari"]),
            ("editor", ["vscode", "vs code", "pycharm", "sublime", "vim", "notepad"]),
            ("theme", ["dark", "light", "system"]),
            ("verbosity", ["concise", "detailed", "brief", "verbose"]),
        ]

        active_records = self._store.list_records(memory_type=memory_type, status=MemoryStatus.ACTIVE)
        conflicts: List[MemoryRecord] = []

        content_lower = content.lower()
        for domain_name, options in preference_domains:
            if domain_name in content_lower or any(opt in content_lower for opt in options):
                for rec in active_records:
                    rec_lower = rec.content.lower()
                    if domain_name in rec_lower or any(opt in rec_lower for opt in options):
                        conflicts.append(rec)

        return conflicts

    async def get_memory(self, memory_id: str) -> Optional[MemoryRecord]:
        """Retrieve a specific memory record by ID."""
        return self._store.get(memory_id)

    async def delete_memory(self, memory_id: str, reason: str = "user_command") -> bool:
        """Mark a memory record as deleted."""
        deleted = self._store.delete(memory_id)
        if deleted:
            await self._publish(
                MemoryDeletedEvent(
                    memory_id=memory_id,
                    reason=reason,
                )
            )
        return deleted

    async def recall_relevant_memories(
        self,
        query: str,
        limit: Optional[int] = None,
        max_tokens: Optional[int] = None,
    ) -> List[MemoryRecord]:
        """Bounded retrieval of relevant active memories ranked by recency, confidence, and confirmation."""
        max_records = limit or self._config.memory_max_context_records
        token_ceiling = max_tokens or self._config.memory_max_context_tokens

        # Search active records
        records = self._store.search(
            query=query,
            limit=max_records * 2,
            active_only=True,
        )

        # Deterministic Ranking: user_confirmed first, then confidence, then recency
        records.sort(
            key=lambda r: (1 if r.user_confirmed else 0, r.confidence, r.updated_at),
            reverse=True,
        )

        # Bounded token estimation (approx 4 chars per token)
        selected: List[MemoryRecord] = []
        accumulated_tokens = 0

        for r in records:
            est_tokens = len(r.content) // 4 + 10
            if accumulated_tokens + est_tokens > token_ceiling:
                break
            selected.append(r)
            accumulated_tokens += est_tokens
            if len(selected) >= max_records:
                break

        await self._publish(
            MemoryRetrievedEvent(
                query_length=len(query),
                records_retrieved=len(selected),
            )
        )

        return selected

    async def expire_stale_memories(self) -> int:
        """Housekeeping: expire records exceeding their TTL."""
        count = self._store.expire_records()
        if count > 0:
            await self._publish(MemoryExpiredEvent())
        return count

    async def clear_memories(self, memory_type: Optional[MemoryType] = None) -> int:
        """Clear memory records (optionally scoped to a specific category)."""
        count = self._store.clear(memory_type=memory_type)
        await self._publish(
            MemoryClearedEvent(
                memory_type=memory_type.value if memory_type else None,
                records_cleared=count,
            )
        )
        return count
