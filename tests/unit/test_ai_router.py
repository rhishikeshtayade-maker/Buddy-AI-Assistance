"""Unit tests for BUDDY AI Router."""

import unittest
from app.ai import (
    AIProviderError,
    AIRouter,
    CloudAIProvider,
    LocalAIProvider,
    MockAIProvider,
)
from app.core import BuddyConfig


class TestAIRouter(unittest.TestCase):
    """Test suite verifying AI Router selection, registration, and fallbacks."""

    def setUp(self) -> None:
        self.config = BuddyConfig(ai_provider="mock", ai_model="mock-v1")
        self.router = AIRouter(self.config)

    def test_default_mock_selection(self) -> None:
        """Verify mock provider is resolved by default when configured."""
        provider = self.router.get_provider()
        self.assertIsInstance(provider, MockAIProvider)
        self.assertEqual(provider.provider_name, "mock")

    def test_cloud_selection(self) -> None:
        """Verify cloud provider is resolved explicitly."""
        provider = self.router.get_provider("cloud")
        self.assertIsInstance(provider, CloudAIProvider)
        self.assertEqual(provider.provider_name, "cloud")

    def test_local_selection(self) -> None:
        """Verify local provider is resolved explicitly."""
        provider = self.router.get_provider("local")
        self.assertIsInstance(provider, LocalAIProvider)
        self.assertEqual(provider.provider_name, "local")

    def test_invalid_provider_raises_error(self) -> None:
        """Verify unknown provider name raises AIProviderError."""
        with self.assertRaises(AIProviderError):
            self.router.get_provider("unknown_vendor_xyz")

    def test_custom_provider_registration(self) -> None:
        """Verify custom provider can be registered and retrieved."""
        custom_mock = MockAIProvider(default_response="Custom mock reply")
        self.router.register_provider("custom", custom_mock)

        self.assertIn("custom", self.router.list_providers())
        retrieved = self.router.get_provider("custom")
        self.assertIs(retrieved, custom_mock)


if __name__ == "__main__":
    unittest.main()
