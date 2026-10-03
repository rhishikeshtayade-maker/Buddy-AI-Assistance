"""Unit tests for MemoryService lifecycle, conflict resolution, and bounded recall."""

from __future__ import annotations

import unittest

from app.core.config import BuddyConfig
from app.core.events import EventBus
from app.core.exceptions import MemoryPolicyViolationError
from app.memory.events import MemoryConflictDetectedEvent, MemoryCreatedEvent
from app.memory.models import MemorySource, MemoryStatus, MemoryType
from app.memory.policy import MemoryPolicy
from app.memory.service import MemoryService
from app.memory.store import SqliteMemoryStore


class TestMemoryService(unittest.IsolatedAsyncioTestCase):
    """Test memory recording, policy checks, conflict resolution, and bounded recall."""

    async def asyncSetUp(self) -> None:
        self.config = BuddyConfig()
        self.store = SqliteMemoryStore(db_path=":memory:")
        self.policy = MemoryPolicy(self.config)
        self.event_bus = EventBus()
        self.service = MemoryService(
            store=self.store,
            policy=self.policy,
            event_bus=self.event_bus,
            config=self.config,
        )

    async def asyncTearDown(self) -> None:
        self.store.close()
        await self.event_bus.shutdown()

    async def test_record_valid_memory(self) -> None:
        rec = await self.service.record_memory(
            content="Call me Rishi",
            memory_type=MemoryType.PROFILE,
            source=MemorySource.USER_EXPLICIT,
        )
        self.assertEqual(rec.content, "Call me Rishi")
        self.assertTrue(rec.user_confirmed)

    async def test_record_secret_rejected_by_policy(self) -> None:
        with self.assertRaises(MemoryPolicyViolationError):
            await self.service.record_memory(
                content="My API key is sk-12345678901234567890abcdef",
            )

    async def test_conflict_resolution_archives_older_preference(self) -> None:
        events: list[object] = []
        self.event_bus.subscribe(MemoryConflictDetectedEvent, lambda e: events.append(e))

        rec1 = await self.service.record_memory(
            content="User prefers Chrome browser",
            memory_type=MemoryType.SEMANTIC,
            source=MemorySource.USER_EXPLICIT,
        )
        self.assertEqual(rec1.status, MemoryStatus.ACTIVE)

        # Later, user expresses a contradictory preference
        rec2 = await self.service.record_memory(
            content="User prefers Firefox browser",
            memory_type=MemoryType.SEMANTIC,
            source=MemorySource.USER_EXPLICIT,
        )

        # Older memory should now be archived
        older = await self.service.get_memory(rec1.memory_id)
        assert older is not None
        self.assertEqual(older.status, MemoryStatus.ARCHIVED)

        # Newer memory is active
        newer = await self.service.get_memory(rec2.memory_id)
        assert newer is not None
        self.assertEqual(newer.status, MemoryStatus.ACTIVE)
        self.assertEqual(len(events), 1)

    async def test_bounded_recall(self) -> None:
        for i in range(15):
            await self.service.record_memory(f"Preference {i} related to Python")

        recalled = await self.service.recall_relevant_memories("Python", limit=5)
        self.assertEqual(len(recalled), 5)


if __name__ == "__main__":
    unittest.main()
