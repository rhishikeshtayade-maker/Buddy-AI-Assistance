"""Integration tests for BUDDY Secret Vault Subsystem (Loop 11).

Tests integration of SecretVaultService with AuditLogger, HealthManager,
LifecycleManager, and Long-Term Memory Encrypted Store.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from app.core.config import BuddyConfig
from app.core.health import HealthManager, HealthStatus
from app.core.lifecycle import LifecycleManager
from app.memory.encryption import get_memory_encryptor
from app.memory.models import MemoryRecord
from app.memory.store import SqliteMemoryStore
from app.security.audit import AuditLogger
from app.security.secrets.health import create_secret_vault_health_check
from app.security.secrets.key_manager import BUDDY_MEMORY_ENCRYPTION_KEY
from app.security.secrets.mock import MockSecretProvider
from app.security.secrets.models import SecretAccessType, SecretSensitivity
from app.security.secrets.service import SecretVaultService
from app.security.secrets.windows_dpapi import WindowsDPAPIProvider


class TestSecretsIntegrationWithAuditAndHealth(unittest.TestCase):
    """Test SecretVaultService integration with AuditLogger and HealthManager."""

    def test_audit_event_emission_for_all_vault_operations(self) -> None:
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            log_path = Path(f.name)

        try:
            audit = AuditLogger(log_path=log_path)
            provider = MockSecretProvider()
            service = SecretVaultService(provider=provider, audit_logger=audit)

            # 1. Store
            service.store_secret("BUDDY_INT_KEY", "value_1", metadata={"test": True})
            # 2. Retrieve
            with service.access_secret("BUDDY_INT_KEY", SecretAccessType.SECRET_USE) as _:
                pass
            # 3. Rotate
            service.rotate_secret("BUDDY_INT_KEY", "value_2")
            # 4. Redact
            service.redact("Here is a leaked sk-proj-123456789012345678901234567890")
            # 5. Access Denied
            try:
                with service.access_secret("BUDDY_INT_KEY", SecretAccessType.SECRET_DISCLOSURE):
                    pass
            except Exception:
                pass
            # 6. Delete
            service.delete_secret("BUDDY_INT_KEY")

            log_text = log_path.read_text(encoding="utf-8")
            self.assertIn("SECRET_STORED", log_text)
            self.assertIn("SECRET_RETRIEVED", log_text)
            self.assertIn("SECRET_ROTATED", log_text)
            self.assertIn("SECRET_REDACTED", log_text)
            self.assertIn("SECRET_ACCESS_DENIED", log_text)
            self.assertIn("SECRET_DELETED", log_text)
            # Ensure zero secret leakage in audit
            self.assertNotIn("value_1", log_text)
            self.assertNotIn("value_2", log_text)
            self.assertNotIn("sk-proj-1234567890", log_text)
        finally:
            if log_path.exists():
                log_path.unlink()

    def test_health_manager_integration(self) -> None:
        provider = MockSecretProvider()
        service = SecretVaultService(provider=provider)
        health_check = create_secret_vault_health_check(service)

        health_mgr = HealthManager()
        health_mgr.register_check("secret_vault", health_check)

        res = asyncio.run(health_mgr.run_check("secret_vault"))
        self.assertEqual(res.status, HealthStatus.HEALTHY)
        self.assertEqual(res.details.get("provider"), "mock_vault")


class TestLifecycleManagerSecretsIntegration(unittest.TestCase):
    """Test full application lifecycle startup and shutdown with SecretVaultService."""

    def test_lifecycle_startup_registers_vault_and_shuts_down_cleanly(self) -> None:
        async def _run():
            with tempfile.TemporaryDirectory() as td:
                cfg = BuddyConfig(
                    secrets_vault_enabled=True,
                    secrets_vault_dir=Path(td),
                    tools_enabled=False,
                    context_awareness_enabled=False,
                )
                lifecycle = LifecycleManager(config=cfg)
                await lifecycle.initialize()

                # Verify registered in service registry
                vault_svc = lifecycle.service_registry.get("secret_vault")
                self.assertIsNotNone(vault_svc)
                self.assertIsInstance(vault_svc, SecretVaultService)

                # Verify health check registered
                report = await lifecycle.health_manager.run_all_checks()
                self.assertIn("security.secret_vault", report.checks)
                self.assertEqual(report.checks["security.secret_vault"].status, HealthStatus.HEALTHY)

                # Store a secret and verify shutdown zeroizes
                vault_svc.store_secret("LIFECYCLE_KEY", "lifecycle_val")
                await lifecycle.shutdown()
                self.assertEqual(len(vault_svc.lifecycle_manager._active_containers), 0)

        asyncio.run(_run())


class TestMemoryMigrationIntegration(unittest.TestCase):
    """Test legacy memory key migration into native vault and encrypted SQLite store."""

    def test_legacy_env_key_migrates_and_encrypts_store(self) -> None:
        provider = MockSecretProvider()
        service = SecretVaultService(provider=provider)

        legacy_passphrase = "my_custom_legacy_memory_passphrase"
        os.environ["BUDDY_MEMORY_KEY"] = legacy_passphrase

        try:
            cfg = BuddyConfig(memory_encryption_enabled=True)
            encryptor = get_memory_encryptor(cfg, vault_service=service)

            # Memory key must now exist in native vault
            self.assertTrue(service.exists(BUDDY_MEMORY_ENCRYPTION_KEY))

            # Plaintext content must be encrypted in SQLite
            store = SqliteMemoryStore(db_path=":memory:", encryptor=encryptor)
            rec = MemoryRecord(content="Secret user health history")
            store.save(rec)

            cursor = store._conn.cursor()
            cursor.execute("SELECT content FROM memory_records WHERE memory_id = ?;", (rec.memory_id,))
            row = cursor.fetchone()
            self.assertNotEqual(row[0], "Secret user health history")

            loaded = store.get(rec.memory_id)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.content, "Secret user health history")

        finally:
            os.environ.pop("BUDDY_MEMORY_KEY", None)


if __name__ == "__main__":
    unittest.main()
