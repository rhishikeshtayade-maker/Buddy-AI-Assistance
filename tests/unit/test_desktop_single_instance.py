"""Unit tests for BUDDY Single Instance Guard."""

import unittest
import uuid

from app.desktop.single_instance import SingleInstanceGuard


class TestSingleInstanceGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.test_name = f"BUDDY-Test-{uuid.uuid4().hex[:8]}"

    def test_single_instance_acquisition_and_exclusion(self) -> None:
        guard1 = SingleInstanceGuard(name=self.test_name)
        guard2 = SingleInstanceGuard(name=self.test_name)

        try:
            # First instance succeeds
            self.assertTrue(guard1.acquire())
            self.assertTrue(guard1.acquired)

            # Second instance fails to acquire duplicate lock
            self.assertFalse(guard2.acquire())
            self.assertFalse(guard2.acquired)

            # Release first instance
            guard1.release()
            self.assertFalse(guard1.acquired)

            # Now second instance can acquire
            self.assertTrue(guard2.acquire())
            self.assertTrue(guard2.acquired)
        finally:
            guard1.release()
            guard2.release()

    def test_context_manager(self) -> None:
        guard = SingleInstanceGuard(name=self.test_name)
        with guard:
            self.assertTrue(guard.acquired)
        self.assertFalse(guard.acquired)
