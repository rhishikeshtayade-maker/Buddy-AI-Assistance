"""Unit tests for BUDDY Secret Vault and Native Credential Management (Loop 11)."""

from __future__ import annotations

import base64
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from app.core.health import HealthStatus
from app.security.secrets.exceptions import (
    CredentialManagerError,
    DPAPIError,
    SecretAccessDeniedError,
    SecretError,
    SecretMigrationError,
    SecretNotFoundError,
    SecretStorageError,
    VaultUnavailableError,
)
from app.security.secrets.key_manager import BUDDY_MEMORY_ENCRYPTION_KEY, KeyManager
from app.security.secrets.lifecycle import SecretLifecycleManager
from app.security.secrets.migration import KeyMigrator
from app.security.secrets.mock import MockSecretProvider
from app.security.secrets.models import (
    SecretAccessType,
    SecretContainer,
    SecretMetadata,
    SecretRotationResult,
    SecretSensitivity,
)
from app.security.secrets.redaction import (
    REDACTED_SECRET,
    redact_string,
    redact_structure,
)
from app.security.secrets.registry import SecretProviderRegistry
from app.security.secrets.service import SecretVaultService
from app.security.secrets.windows_dpapi import WindowsDPAPIProvider


class TestSecretModelsAndContainers(unittest.TestCase):
    """Test SecretMetadata and SecretContainer security properties."""

    def test_metadata_repr_does_not_leak_secret(self) -> None:
        meta = SecretMetadata(
            identifier="BUDDY_TEST_KEY",
            provider="windows_dpapi",
            version=1,
        )
        repr_str = repr(meta)
        str_str = str(meta)
        self.assertIn("BUDDY_TEST_KEY", repr_str)
        self.assertIn("windows_dpapi", repr_str)
        self.assertEqual(repr_str, str_str)

    def test_container_zeroization_and_destruction(self) -> None:
        secret_val = "super-secret-token-12345"
        container = SecretContainer("BUDDY_TEST_TOKEN", secret_val)

        # Before destruction
        self.assertEqual(container.get_secret_value(), secret_val)
        self.assertFalse(container.is_destroyed)
        self.assertNotIn(secret_val, repr(container))
        self.assertNotIn(secret_val, str(container))
        self.assertIn("[VALUE PROTECTED]", repr(container))

        # Explicit zeroization
        container.zeroize()
        self.assertTrue(container.is_destroyed)
        with self.assertRaises(RuntimeError):
            container.get_secret_value()

    def test_container_context_manager_auto_zeroization(self) -> None:
        secret_val = "context-managed-secret-999"
        with SecretContainer("BUDDY_CTX_KEY", secret_val) as container:
            self.assertEqual(container.get_secret_value(), secret_val)
            self.assertFalse(container.is_destroyed)

        # Container should be destroyed upon exiting context
        self.assertTrue(container.is_destroyed)
        with self.assertRaises(RuntimeError):
            container.get_secret_value()


class TestRedactionSubsystem(unittest.TestCase):
    """Test comprehensive regex scrubbing of credentials across all supported formats."""

    def test_redact_api_keys(self) -> None:
        cases = [
            ("sk-1234567890abcdef1234567890abcdef", REDACTED_SECRET),
            ("sk-proj-abcde123456789012345678901234567890", REDACTED_SECRET),
            ("sk-ant-123456789012345678901234567890", REDACTED_SECRET),
            ("AIzaSyD-123456789012345678901234567890", REDACTED_SECRET),
            ("ghp_123456789012345678901234567890123456", REDACTED_SECRET),
            ("AKIAIOSFODNN7EXAMPLE", REDACTED_SECRET),
        ]
        for raw, expected in cases:
            redacted = redact_string(raw)
            self.assertEqual(redacted, expected)
            self.assertNotIn(raw, redacted)

    def test_redact_authorization_and_jwt(self) -> None:
        header = "Authorization: Bearer mysecretbearertoken1234567890"
        redacted_hdr = redact_string(header)
        self.assertNotIn("mysecretbearertoken1234567890", redacted_hdr)
        self.assertIn(REDACTED_SECRET, redacted_hdr)

        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozG4B_wP_example_sig123456"
        redacted_jwt = redact_string(jwt)
        self.assertEqual(redacted_jwt, REDACTED_SECRET)

    def test_redact_passwords_pin_otp_cookies(self) -> None:
        text = "password=SuperSecretPassword123 pin=1234 otp: 567890 connect.sid=sessiontoken1234567890"
        redacted = redact_string(text)
        self.assertNotIn("SuperSecretPassword123", redacted)
        self.assertNotIn("1234", redacted)
        self.assertNotIn("567890", redacted)
        self.assertNotIn("sessiontoken1234567890", redacted)

    def test_redact_nested_structures(self) -> None:
        nested_data = {
            "user": "alice",
            "api_key": "sk-proj-supersecret12345678901234567890",
            "details": {
                "token": "secret_jwt_token_1234567890",
                "settings": {"mode": "dark"},
            },
            "credentials": ["password123", "normal_data"],
        }
        cleaned = redact_structure(nested_data)
        self.assertEqual(cleaned["user"], "alice")
        self.assertEqual(cleaned["api_key"], REDACTED_SECRET)
        self.assertEqual(cleaned["details"]["token"], REDACTED_SECRET)
        self.assertEqual(cleaned["details"]["settings"]["mode"], "dark")
        self.assertEqual(cleaned["credentials"], REDACTED_SECRET)


class TestMockSecretProvider(unittest.TestCase):
    """Test MockSecretProvider in isolation."""

    def setUp(self) -> None:
        self.provider = MockSecretProvider()

    def test_store_retrieve_and_delete(self) -> None:
        meta = self.provider.store("BUDDY_KEY", "value_123")
        self.assertEqual(meta.version, 1)
        self.assertTrue(self.provider.exists("BUDDY_KEY"))

        val = self.provider.retrieve("BUDDY_KEY")
        self.assertEqual(val, "value_123")

        # Deletion
        deleted = self.provider.delete("BUDDY_KEY")
        self.assertTrue(deleted)
        self.assertFalse(self.provider.exists("BUDDY_KEY"))

        with self.assertRaises(SecretNotFoundError):
            self.provider.retrieve("BUDDY_KEY")

    def test_rotation(self) -> None:
        self.provider.store("ROT_KEY", "initial_val")
        result = self.provider.rotate("ROT_KEY", "new_val")
        self.assertTrue(result.success)
        self.assertEqual(result.old_version, 1)
        self.assertEqual(result.new_version, 2)
        self.assertEqual(self.provider.retrieve("ROT_KEY"), "new_val")

    def test_health_check(self) -> None:
        health = self.provider.health()
        self.assertEqual(health.status, HealthStatus.HEALTHY)
        self.provider.set_healthy(False)
        self.assertEqual(self.provider.health().status, HealthStatus.UNHEALTHY)


class TestSecretVaultServiceUnit(unittest.TestCase):
    """Test SecretVaultService core logic with mock backend."""

    def setUp(self) -> None:
        self.mock_provider = MockSecretProvider()
        self.service = SecretVaultService(provider=self.mock_provider)

    def test_invalid_identifier_rejected(self) -> None:
        with self.assertRaises(SecretError):
            self.service.store_secret("", "secret_val")
        with self.assertRaises(SecretError):
            self.service.store_secret("bad identifier with spaces", "secret_val")
        with self.assertRaises(SecretError):
            # Raw API key as identifier rejected
            self.service.store_secret("sk-proj-123456789012345678901234567890", "secret_val")

    def test_empty_secret_value_rejected(self) -> None:
        with self.assertRaises(SecretError):
            self.service.store_secret("VALID_ID", "")

    def test_secret_use_vs_disclosure_boundary(self) -> None:
        self.service.store_secret("BUDDY_BOUNDED_SECRET", "super_secret_value")

        # SECRET_USE is permitted within context manager
        with self.service.access_secret("BUDDY_BOUNDED_SECRET", SecretAccessType.SECRET_USE) as val:
            self.assertEqual(val, "super_secret_value")

        # SECRET_DISCLOSURE is strictly denied
        with self.assertRaises(SecretAccessDeniedError):
            with self.service.access_secret("BUDDY_BOUNDED_SECRET", SecretAccessType.SECRET_DISCLOSURE) as val:
                pass

    def test_direct_retrieval_internal_boundary(self) -> None:
        self.service.store_secret("BUDDY_INTERNAL_KEY", "direct_val_456")
        retrieved = self.service.retrieve_secret_value("BUDDY_INTERNAL_KEY", purpose="internal_cipher")
        self.assertEqual(retrieved, "direct_val_456")

    def test_delete_and_exists(self) -> None:
        self.service.store_secret("TO_BE_DELETED", "del_val")
        self.assertTrue(self.service.exists("TO_BE_DELETED"))
        self.assertTrue(self.service.delete_secret("TO_BE_DELETED"))
        self.assertFalse(self.service.exists("TO_BE_DELETED"))


class TestKeyManagerAndMigrator(unittest.TestCase):
    """Test KeyManager generation and KeyMigrator fail-closed behavior."""

    def setUp(self) -> None:
        self.provider = MockSecretProvider()
        self.key_manager = KeyManager(self.provider)
        self.migrator = KeyMigrator(self.provider)

    def test_generate_and_get_or_create_key(self) -> None:
        key1 = self.key_manager.get_or_create_key("TEST_CRYPTO_KEY")
        self.assertTrue(len(key1) > 20)
        # Should return same key when queried again
        key2 = self.key_manager.get_or_create_key("TEST_CRYPTO_KEY")
        self.assertEqual(key1, key2)

    def test_atomic_key_rotation(self) -> None:
        old_k = self.key_manager.get_or_create_key("ROT_CRYPTO_KEY")
        rot_res = self.key_manager.rotate_key("ROT_CRYPTO_KEY")
        self.assertTrue(rot_res.success)
        self.assertEqual(rot_res.new_version, 2)
        new_k = self.provider.retrieve("ROT_CRYPTO_KEY")
        self.assertNotEqual(old_k, new_k)

    def test_migrate_memory_key_from_env(self) -> None:
        os.environ["BUDDY_MEMORY_KEY"] = "legacy_test_passphrase_123"
        try:
            migrated = self.migrator.migrate_memory_encryption_key(legacy_env_var="BUDDY_MEMORY_KEY")
            self.assertTrue(self.provider.exists(BUDDY_MEMORY_ENCRYPTION_KEY))
            self.assertEqual(self.provider.retrieve(BUDDY_MEMORY_ENCRYPTION_KEY), migrated)
        finally:
            os.environ.pop("BUDDY_MEMORY_KEY", None)

    def test_migrate_memory_key_from_file_and_unlink(self) -> None:
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("legacy_file_passphrase_456")
            temp_path = Path(f.name)

        try:
            self.assertTrue(temp_path.exists())
            migrated = self.migrator.migrate_memory_encryption_key(
                legacy_env_var="NONEXISTENT_VAR_123",
                legacy_file_path=temp_path,
            )
            self.assertTrue(self.provider.exists(BUDDY_MEMORY_ENCRYPTION_KEY))
            # Plaintext file must be safely unlinked/removed after migration
            self.assertFalse(temp_path.exists())
        finally:
            if temp_path.exists():
                temp_path.unlink()


if __name__ == "__main__":
    unittest.main()
