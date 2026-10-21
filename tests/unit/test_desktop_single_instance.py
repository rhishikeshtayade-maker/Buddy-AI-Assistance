"""Unit tests for BUDDY Single Instance Guard.

Verifies:
1. First instance acquires single instance ownership.
2. Second instance fails to acquire duplicate lock.
3. Release and re-acquisition cycle works repeatedly.
4. Calling release on an unacquired guard does not close or invalidate an active guard.
5. Idempotent acquire() and release() behavior.
6. Context manager semantics.
"""

from __future__ import annotations

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

    def test_repeated_acquisition_and_release(self) -> None:
        """Verify repeated acquire/release cycles work reliably."""
        guard = SingleInstanceGuard(name=self.test_name)
        for _ in range(3):
            self.assertTrue(guard.acquire())
            self.assertTrue(guard.acquired)
            guard.release()
            self.assertFalse(guard.acquired)

    def test_failed_guard_release_does_not_affect_active_guard(self) -> None:
        """Releasing an unacquired/rejected guard must never close an active guard's mutex."""
        active_guard = SingleInstanceGuard(name=self.test_name)
        rejected_guard = SingleInstanceGuard(name=self.test_name)
        third_guard = SingleInstanceGuard(name=self.test_name)

        try:
            self.assertTrue(active_guard.acquire())

            # rejected_guard fails
            self.assertFalse(rejected_guard.acquire())

            # Attempting to release rejected_guard must be a safe no-op
            rejected_guard.release()

            # active_guard must still be active and exclusive
            self.assertTrue(active_guard.acquired)
            self.assertFalse(third_guard.acquire())

            # Once active_guard releases, third_guard can acquire
            active_guard.release()
            self.assertTrue(third_guard.acquire())
        finally:
            active_guard.release()
            rejected_guard.release()
            third_guard.release()

    def test_idempotent_acquire_and_release(self) -> None:
        """Calling acquire() multiple times on the same guard returns True; repeated release() is safe."""
        guard = SingleInstanceGuard(name=self.test_name)
        try:
            self.assertTrue(guard.acquire())
            # Second call on same guard returns True without error
            self.assertTrue(guard.acquire())
            self.assertTrue(guard.acquired)

            guard.release()
            self.assertFalse(guard.acquired)
            # Repeated release is a safe no-op
            guard.release()
            self.assertFalse(guard.acquired)
        finally:
            guard.release()

    def test_context_manager(self) -> None:
        guard = SingleInstanceGuard(name=self.test_name)
        with guard:
            self.assertTrue(guard.acquired)
        self.assertFalse(guard.acquired)
