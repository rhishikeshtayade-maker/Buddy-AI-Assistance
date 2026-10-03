"""Unit tests for Memory Retrieval bounded constraints, ranking, and TTL filtering."""

from __future__ import annotations

import time
import unittest

from app.core.config import BuddyConfig
from app.memory.models import MemoryRecord, MemorySource, MemoryStatus, MemoryType
from app.memory.service import MemoryService
from app.memory.store import SqliteMemoryStore


class TestMemoryRetrieval(unittest.IsolatedAsyncioTestCase):
    """Test deterministic ranking, exclusion of expired/deleted records, and token limits."""

    async def asyncSetUp(self) -> None:
        self.config = BuddyConfig(memory_max_context_records=5, memory_max_context_tokens=100)
        self.store = SqliteMemoryStore(db_path=":memory:")
        self.service = MemoryService(store=self.store, config=self.config)

    async def asyncTearDown(self) -> None:
        self.store.close()

    async def test_expired_and_deleted_records_excluded_from_recall(self) -> None:
        now = time.time()
        active_rec = MemoryRecord(content="Active note regarding compiler")
        expired_rec = MemoryRecord(content="Expired note regarding compiler", expires_at=now - 100.0)
        deleted_rec = MemoryRecord(content="Deleted note regarding compiler", status=MemoryStatus.DELETED)

        self.store.save(active_rec)
        self.store.save(expired_rec)
        self.store.save(deleted_rec)

        recalled = await self.service.recall_relevant_memories("compiler")
        self.assertEqual(len(recalled), 1)
        self.assertEqual(recalled[0].memory_id, active_rec.memory_id)

    async def test_deterministic_ranking_user_confirmed_first(self) -> None:
        rec_inferred = MemoryRecord(
            content="Inferred fact about python tools",
            source=MemorySource.AI_INFERRED,
            user_confirmed=False,
            confidence=0.9,
        )
        rec_confirmed = MemoryRecord(
            content="Confirmed fact about python tools",
            source=MemorySource.USER_EXPLICIT,
            user_confirmed=True,
            confidence=0.8,
        )

        self.store.save(rec_inferred)
        self.store.save(rec_confirmed)

        recalled = await self.service.recall_relevant_memories("python")
        self.assertEqual(len(recalled), 2)
        # Confirmed memory should rank first regardless of lower raw confidence
        self.assertEqual(recalled[0].memory_id, rec_confirmed.memory_id)


if __name__ == "__main__":
    unittest.main()
