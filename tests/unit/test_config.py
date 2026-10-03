"""Unit tests for BUDDY Typed Configuration and Secret Masking."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import BuddyConfig, ConfigurationError, REDACTED_MASK


class TestBuddyConfig(unittest.TestCase):
    """Test suite verifying typed settings, validation, env override, and redaction."""

    def test_default_configuration(self) -> None:
        """Verify default values meet architecture requirements."""
        config = BuddyConfig()
        self.assertEqual(config.app_env, "development")
        self.assertEqual(config.log_level, "INFO")
        self.assertEqual(config.buddy_name, "BUDDY")
        self.assertEqual(config.ai_provider, "mock")
        self.assertEqual(config.stt_provider, "mock")
        self.assertEqual(config.tts_provider, "mock")
        self.assertEqual(config.master_key_storage, "keyring")

    def test_environment_variable_override(self) -> None:
        """Verify environment variables properly configure settings."""
        env_vars = {
            "APP_ENV": "production",
            "LOG_LEVEL": "WARNING",
            "BUDDY_NAME": "BuddyTest",
            "AI_PROVIDER": "anthropic",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            config = BuddyConfig.load_from_env()
            self.assertEqual(config.app_env, "production")
            self.assertEqual(config.log_level, "WARNING")
            self.assertEqual(config.buddy_name, "BuddyTest")
            self.assertEqual(config.ai_provider, "anthropic")

    def test_buddy_prefix_fallback(self) -> None:
        """Verify BUDDY_ENV and BUDDY_LOG_LEVEL aliases fall back properly."""
        env_vars = {
            "BUDDY_ENV": "testing",
            "BUDDY_LOG_LEVEL": "DEBUG",
        }
        with patch.dict(os.environ, env_vars, clear=False):
            # Ensure APP_ENV and LOG_LEVEL are not explicitly in os.environ
            os.environ.pop("APP_ENV", None)
            os.environ.pop("LOG_LEVEL", None)

            config = BuddyConfig.load_from_env()
            self.assertEqual(config.app_env, "testing")
            self.assertEqual(config.log_level, "DEBUG")

    def test_invalid_log_level_rejected(self) -> None:
        """Verify invalid log level raises validation error."""
        with self.assertRaises(Exception):
            BuddyConfig(log_level="VERBOSE")  # type: ignore

    def test_invalid_app_env_rejected(self) -> None:
        """Verify invalid app env raises validation error."""
        with self.assertRaises(Exception):
            BuddyConfig(app_env="invalid_env")  # type: ignore

    def test_secret_redaction(self) -> None:
        """Verify to_safe_dict masks any sensitive keys with REDACTED_MASK."""
        config = BuddyConfig()
        safe_dict = config.to_safe_dict()

        # Check that master_key_storage is redacted because 'key' is in the field name
        self.assertEqual(safe_dict["master_key_storage"], REDACTED_MASK)
        # Check non-sensitive values are preserved
        self.assertEqual(safe_dict["app_env"], "development")
        self.assertEqual(safe_dict["buddy_name"], "BUDDY")


if __name__ == "__main__":
    unittest.main()
