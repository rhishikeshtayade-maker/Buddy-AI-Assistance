"""Unit tests for BUDDY Service Registry."""

import unittest
from app.core import (
    DuplicateServiceError,
    ServiceNotFoundError,
    ServiceRegistry,
)


class DummyService:
    """Dummy class for type-based registration test."""
    pass


class TestServiceRegistry(unittest.TestCase):
    """Test suite verifying service registration, retrieval, and error states."""

    def setUp(self) -> None:
        self.registry = ServiceRegistry()

    def test_register_and_get_by_string(self) -> None:
        """Verify registering and retrieving by string key."""
        dummy = {"key": "value"}
        self.registry.register("my_service", dummy)

        self.assertTrue(self.registry.contains("my_service"))
        retrieved = self.registry.get("my_service")
        self.assertIs(retrieved, dummy)

    def test_register_and_get_by_class_type(self) -> None:
        """Verify registering and retrieving by class type."""
        dummy_instance = DummyService()
        self.registry.register(DummyService, dummy_instance)

        self.assertTrue(self.registry.contains(DummyService))
        retrieved = self.registry.get(DummyService)
        self.assertIs(retrieved, dummy_instance)

    def test_duplicate_registration_raises_without_override(self) -> None:
        """Verify registering duplicate without allow_override raises DuplicateServiceError."""
        self.registry.register("svc", 123)
        with self.assertRaises(DuplicateServiceError):
            self.registry.register("svc", 456)

        # Allow override works
        self.registry.register("svc", 789, allow_override=True)
        self.assertEqual(self.registry.get("svc"), 789)

    def test_missing_service_raises_or_returns_default(self) -> None:
        """Verify get on missing service raises ServiceNotFoundError unless default is supplied."""
        with self.assertRaises(ServiceNotFoundError):
            self.registry.get("nonexistent")

        val = self.registry.get("nonexistent", default="fallback")
        self.assertEqual(val, "fallback")

    def test_remove_service(self) -> None:
        """Verify removing a service."""
        self.registry.register("temp", "data")
        removed = self.registry.remove("temp")
        self.assertEqual(removed, "data")
        self.assertFalse(self.registry.contains("temp"))

        with self.assertRaises(ServiceNotFoundError):
            self.registry.remove("temp")

    def test_clear_services(self) -> None:
        """Verify clearing all registered services."""
        self.registry.register("s1", 1)
        self.registry.register("s2", 2)
        self.registry.clear()
        self.assertEqual(len(self.registry.list_services()), 0)


if __name__ == "__main__":
    unittest.main()
