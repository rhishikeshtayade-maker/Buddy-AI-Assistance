"""End-to-End Tests for BUDDY Native Secret Vault Subsystem (Loop 11).

Verifies full system flows:
1. Native secret lifecycle (store, bounded use, rotation, deletion).
2. End-to-end long-term memory encryption and key migration.
3. AI provider credential isolation and error body redaction.
4. Tool execution credential isolation and output scrubbing.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from app.ai.exceptions import AIAuthenticationError
from app.ai.provider import CloudAIProvider
from app.core.config import BuddyConfig
from app.memory.encryption import get_memory_encryptor
from app.memory.manager import MemoryManager
from app.memory.models import MemoryRecord, MemoryType
from app.memory.service import MemoryService
from app.memory.store import SqliteMemoryStore
from app.security.audit import AuditLogger
from app.security.secrets.key_manager import BUDDY_MEMORY_ENCRYPTION_KEY
from app.security.secrets.models import SecretAccessType, SecretSensitivity
from app.security.secrets.redaction import REDACTED_SECRET, redact_string
from app.security.secrets.service import SecretVaultService
from app.security.secrets.windows_dpapi import WindowsDPAPIProvider
from app.tools.base import Tool
from app.tools.executor import ToolExecutor
from app.tools.models import ToolDefinition, ToolPermissionLevel, ToolRequest, ToolRiskLevel
from app.tools.registry import ToolRegistry


class SyntheticSecretLeakingTool(Tool):
    """Synthetic test tool that attempts to return raw credentials in its output."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="test.synthetic_leak",
            description="Synthetic test tool that outputs sensitive credentials",
            risk_level=ToolRiskLevel.SAFE,
            permission_level=ToolPermissionLevel.NONE,
        )

    async def execute(self, arguments: dict) -> dict:
        return {
            "status": "connected",
            "api_key": "sk-proj-supersecretrawcredential1234567890",
            "access_token": "ghp_1234567890abcdef1234567890abcdef1234",
            "safe_data": "Normal non-sensitive result",
        }

    async def verify(self, arguments: dict, output: dict) -> bool:
        return True


class TestSecretsE2E(unittest.TestCase):
    """End-to-end validation of secret security invariants."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="buddy_e2e_secrets_")
        self.vault_dir = Path(self.temp_dir) / "vault"
        self.audit_log = Path(self.temp_dir) / "audit.log"
        self.audit = AuditLogger(log_path=self.audit_log)
        self.provider = WindowsDPAPIProvider(vault_dir=self.vault_dir)
        self.service = SecretVaultService(provider=self.provider, audit_logger=self.audit)

    def test_e2e_native_secret_lifecycle(self) -> None:
        ident = "BUDDY_E2E_DATABASE_PASS"
        initial_val = "db-password-initial-v1-abcdef12345"
        rotated_val = "db-password-rotated-v2-xyz98765432"

        # 1. Store
        meta1 = self.service.store_secret(
            identifier=ident,
            secret_value=initial_val,
            metadata={"env": "e2e_test"},
            sensitivity=SecretSensitivity.HIGHLY_SENSITIVE,
        )
        self.assertEqual(meta1.version, 1)
        self.assertTrue(self.service.exists(ident))

        # 2. Bounded internal access
        with self.service.access_secret(ident, SecretAccessType.SECRET_USE) as val:
            self.assertEqual(val, initial_val)

        # 3. Rotate
        rot_res = self.service.rotate_secret(ident, rotated_val)
        self.assertTrue(rot_res.success)
        self.assertEqual(rot_res.new_version, 2)

        # Verify rotated value is active
        with self.service.access_secret(ident) as new_val:
            self.assertEqual(new_val, rotated_val)

        # 4. Delete
        deleted = self.service.delete_secret(ident)
        self.assertTrue(deleted)
        self.assertFalse(self.service.exists(ident))

        # 5. Verify audit trail contains zero secret values
        log_content = self.audit_log.read_text(encoding="utf-8")
        self.assertNotIn(initial_val, log_content)
        self.assertNotIn(rotated_val, log_content)
        self.assertIn("SECRET_STORED", log_content)
        self.assertIn("SECRET_ROTATED", log_content)
        self.assertIn("SECRET_DELETED", log_content)

    def test_e2e_memory_encryption_and_migration(self) -> None:
        async def _run():
            legacy_key = "legacy_secret_key_passphrase_for_testing"
            os.environ["BUDDY_MEMORY_KEY"] = legacy_key

            try:
                cfg = BuddyConfig(memory_encryption_enabled=True)
                encryptor = get_memory_encryptor(cfg, vault_service=self.service)

                # Memory key is now stored in native vault
                self.assertTrue(self.service.exists(BUDDY_MEMORY_ENCRYPTION_KEY))

                # Initialize Memory service and store facts
                db_path = Path(self.temp_dir) / "test_memory.db"
                store = SqliteMemoryStore(db_path=db_path, encryptor=encryptor)
                mem_service = MemoryService(store=store, config=cfg)
                mem_manager = MemoryManager(service=mem_service, config=cfg)

                # Record sensitive personal fact
                await mem_manager.remember(
                    content="User prefers privacy-first desktop automation.",
                    memory_type=MemoryType.SEMANTIC,
                )

                # Direct raw SQL query should find encrypted ciphertext, NOT plaintext
                raw_conn = store._conn
                cursor = raw_conn.cursor()
                cursor.execute("SELECT content FROM memory_records;")
                rows = cursor.fetchall()
                self.assertEqual(len(rows), 1)
                stored_ciphertext = rows[0][0]
                self.assertNotIn("User prefers privacy-first", stored_ciphertext)

                # Recall via facade should decrypt correctly
                recalled = await mem_manager.recall("privacy")
                self.assertEqual(len(recalled), 1)
                self.assertEqual(recalled[0].content, "User prefers privacy-first desktop automation.")

            finally:
                os.environ.pop("BUDDY_MEMORY_KEY", None)

        asyncio.run(_run())

    def test_e2e_ai_provider_isolation(self) -> None:
        raw_key = "sk-proj-testkey12345678901234567890abcdef"
        provider = CloudAIProvider(api_key=raw_key)

        # Repr and str must never expose key
        self.assertNotIn(raw_key, repr(provider))
        self.assertNotIn(raw_key, str(provider))

        # Redaction on simulated error text
        simulated_err = f"Failed to authenticate with key: {raw_key} and Bearer {raw_key}"
        redacted_err = redact_string(simulated_err)
        self.assertNotIn(raw_key, redacted_err)
        self.assertIn(REDACTED_SECRET, redacted_err)

    def test_e2e_tool_executor_credential_isolation(self) -> None:
        async def _run():
            registry = ToolRegistry()
            leaking_tool = SyntheticSecretLeakingTool()
            registry.register_tool(leaking_tool)

            executor = ToolExecutor(registry=registry, audit_logger=self.audit)
            req = ToolRequest(tool_name="test.synthetic_leak", arguments={})

            result = await executor.execute(req)
            self.assertTrue(result.success)

            # Output must have been scrubbed
            out = result.output
            self.assertEqual(out["api_key"], REDACTED_SECRET)
            self.assertEqual(out["access_token"], REDACTED_SECRET)
            self.assertEqual(out["safe_data"], "Normal non-sensitive result")
            self.assertNotIn("sk-proj-supersecret", str(out))
            self.assertNotIn("ghp_1234567890", str(out))

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
