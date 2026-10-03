"""Unit tests for deterministic Memory Conflict Resolution."""

from __future__ import annotations

import unittest

from app.core.config import BuddyConfig
from app.memory.models import MemorySource, MemoryStatus, MemoryType
from app.memory.service import MemoryService
from app.memory.store import SqliteMemoryStore


class TestMemoryConflicts(unittest.IsolatedAsyncioTestCase):
    """Test domain conflict detection (browser, editor) and provenance resolution."""

    async def asyncSetUp(self) -> None:
        self.config = BuddyConfig()
        self.store = SqliteMemoryStore(db_path=":memory:")
        self.service = MemoryService(store=self.store, config=self.config)

    async def asyncTearDown(self) -> None:
        self.store.close()

    async def test_editor_conflict_resolution(self) -> None:
        rec1 = await self.service.record_memory(
            content="User prefers VS Code for programming",
            memory_type=MemoryType.SEMANTIC,
            source=MemorySource.USER_EXPLICIT,
        )

        # Later, user explicitly changes editor preference to Sublime
        rec2 = await self.service.record_memory(
            content="User prefers Sublime for programming",
            memory_type=MemoryType.SEMANTIC,
            source=MemorySource.USER_EXPLICIT,
        )

        old = await self.service.get_memory(rec1.memory_id)
        assert old is not None
        self.assertEqual(old.status, MemoryStatus.ARCHIVED)

        new = await self.service.get_memory(rec2.memory_id)
        assert new is not None
        self.assertEqual(new.status, MemoryStatus.ACTIVE)

        # When searching for programming editor, only active one is recalled
        recalled = await self.service.recall_relevant_memories("programming")
        contents = [r.content for r in recalled]
        self.assertIn("User prefers Sublime for programming", contents)
        self.assertNotIn("User prefers VS Code for programming", contents)


if __name__ == "__main__":
    unittest.main()
