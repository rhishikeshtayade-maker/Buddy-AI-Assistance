"""Unit tests for BUDDY Memory Models and Schema Validation."""

from __future__ import annotations

import unittest
from pydantic import ValidationError

from app.memory.models import (
    MemoryCandidate,
    MemoryCommand,
    MemoryCommandAction,
    MemoryRecord,
    MemorySensitivity,
    MemorySource,
    MemoryStatus,
    MemoryType,
)


class TestMemoryModels(unittest.TestCase):
    """Test schema validation, immutability, extra-field prohibition, and defaults."""

    def test_memory_record_valid_creation(self) -> None:
        rec = MemoryRecord(
            content="User prefers dark theme in all applications",
            memory_type=MemoryType.SEMANTIC,
            source=MemorySource.USER_EXPLICIT,
            sensitivity=MemorySensitivity.PERSONAL,
        )
        self.assertTrue(len(rec.memory_id) > 0)
        self.assertEqual(rec.status, MemoryStatus.ACTIVE)
        self.assertEqual(rec.version, 1)
        self.assertEqual(rec.confidence, 1.0)
        self.assertFalse(rec.user_confirmed)

    def test_memory_record_forbids_extra_fields(self) -> None:
        with self.assertRaises(ValidationError):
            MemoryRecord(
                content="Valid content",
                arbitrary_injected_field="malicious_payload",  # type: ignore
            )

    def test_memory_record_empty_content_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            MemoryRecord(content="")

        with self.assertRaises(ValidationError):
            MemoryRecord(content="   \n\t  ")

    def test_memory_candidate_creation(self) -> None:
        cand = MemoryCandidate(
            content="User frequently works with Python files",
            memory_type=MemoryType.SEMANTIC,
            source=MemorySource.AI_INFERRED,
            confidence=0.75,
            tags=["programming", "python"],
        )
        self.assertEqual(cand.confidence, 0.75)
        self.assertEqual(cand.tags, ["programming", "python"])

    def test_memory_command_models(self) -> None:
        cmd = MemoryCommand(
            action=MemoryCommandAction.REMEMBER,
            target_content="My preferred browser is Chrome",
        )
        self.assertEqual(cmd.action, MemoryCommandAction.REMEMBER)
        self.assertEqual(cmd.target_content, "My preferred browser is Chrome")
        self.assertFalse(cmd.confirmation_required)


if __name__ == "__main__":
    unittest.main()
