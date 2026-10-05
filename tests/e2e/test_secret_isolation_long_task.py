"""End-to-End Tests for Secret Isolation During Long-Horizon Tasks (Loop 12 Scenario F).

Scenario F — Secret Isolation:
1. Synthetic secret is stored using the existing Loop 11 secure secret system.
2. Reasoning receives only an opaque reference if a reference is necessary.
3. Raw secret does NOT appear in:
   - Goal
   - Requirements
   - Plan
   - Task steps
   - Checkpoints
   - Reasoning metadata
   - Memory
   - Audit logs
   - Exceptions
   - Normal tool output
4. Raw secret cannot be recovered through the reasoning layer.
5. Secret lifecycle remains controlled by Loop 11.
6. No secret-provider bypass exists.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.agent.models import Task, TaskStep
from app.agent.reasoning.models import (
    Checkpoint,
    Goal,
    GoalRequirement,
    GoalStatus,
)
from app.agent.reasoning.orchestrator import LongHorizonOrchestrator
from app.core.config import BuddyConfig
from app.memory.encryption import get_memory_encryptor
from app.memory.manager import MemoryManager
from app.memory.models import MemoryType
from app.memory.service import MemoryService
from app.memory.store import SqliteMemoryStore
from app.security.audit import AuditLogger
from app.security.path_policy import PathPolicy
from app.security.secrets.models import SecretAccessType, SecretSensitivity
from app.security.secrets.redaction import REDACTED_SECRET, redact_string
from app.security.secrets.service import SecretVaultService
from app.security.secrets.windows_dpapi import WindowsDPAPIProvider
from app.tools.base import Tool
from app.tools.builtin import FileCreateTool
from app.tools.executor import ToolExecutor
from app.tools.models import (
    ToolDefinition,
    ToolExecutionStatus,
    ToolPermissionLevel,
    ToolRequest,
    ToolRiskLevel,
)
from app.tools.registry import ToolRegistry


class SyntheticSecretConsumingTool(Tool):
    """Tool that consumes an opaque secret reference and uses the vault internally."""

    def __init__(self, vault: SecretVaultService):
        self._vault = vault

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="cloud.sync_data",
            description="Syncs data using an opaque secret reference",
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
        )

    async def execute(self, arguments: dict) -> dict:
        secret_ref = arguments.get("secret_ref")
        # In a real tool, it resolves the secret in memory via the vault
        if not secret_ref or not self._vault.exists(secret_ref):
            return {"status": "error", "error": f"Secret reference '{secret_ref}' not found"}

        with self._vault.access_secret(secret_ref, SecretAccessType.SECRET_USE) as raw_secret:
            # Internal bounded operation using raw_secret
            operation_successful = len(raw_secret) > 0

        # Normal tool output returns only status and safe opaque metadata — NEVER raw secret
        return {
            "status": "success",
            "synced_items": 42,
            "secret_identifier": secret_ref,
        }

    async def verify(self, arguments: dict, output: dict) -> bool:
        return output.get("status") == "success"


class SyntheticSecretLeakingTool(Tool):
    """Tool that maliciously or accidentally attempts to leak raw secrets in output and exceptions."""

    def __init__(self, raw_secret: str):
        self._raw_secret = raw_secret

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="test.synthetic_leak_secret",
            description="Tool attempting to return secret in output or throw it",
            risk_level=ToolRiskLevel.SAFE,
            permission_level=ToolPermissionLevel.NONE,
        )

    async def execute(self, arguments: dict) -> dict:
        if arguments.get("raise_exception"):
            raise RuntimeError(f"Authentication failed with key: {self._raw_secret}")
        return {
            "token": self._raw_secret,
            "api_key": self._raw_secret,
            "info": f"Bearer {self._raw_secret}",
        }

    async def verify(self, arguments: dict, output: dict) -> bool:
        return True


class TestSecretIsolationLongTaskE2E(unittest.IsolatedAsyncioTestCase):
    """Scenario F: E2E Secret Isolation during Long-Horizon Reasoning."""

    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp(prefix="buddy_e2e_sec_iso_")
        self.workspace = Path(self.temp_dir)
        self.vault_dir = self.workspace / "vault"
        self.audit_log = self.workspace / "audit.log"
        self.audit = AuditLogger(log_path=self.audit_log)

        # 1. Native Loop 11 vault system
        self.provider = WindowsDPAPIProvider(vault_dir=self.vault_dir)
        self.vault = SecretVaultService(provider=self.provider, audit_logger=self.audit)

        # Synthetic test secret (NEVER real credentials)
        self.secret_ref = "SYNTHETIC_E2E_SERVICE_KEY"
        self.raw_secret = "sk-proj-syntheticsecrettesttoken1234567890abcdef"

        # Store in vault
        self.vault.store_secret(
            identifier=self.secret_ref,
            secret_value=self.raw_secret,
            sensitivity=SecretSensitivity.HIGHLY_SENSITIVE,
        )

        # Registry & Tools
        self.registry = ToolRegistry()
        self.policy = PathPolicy(allowed_roots=[self.workspace])
        self.registry.register_tool(FileCreateTool(self.policy))
        self.sync_tool = SyntheticSecretConsumingTool(self.vault)
        self.leak_tool = SyntheticSecretLeakingTool(self.raw_secret)
        self.registry.register_tool(self.sync_tool)
        self.registry.register_tool(self.leak_tool)

        self.tool_executor = ToolExecutor(
            registry=self.registry,
            audit_logger=self.audit,
        )

        self.orchestrator = LongHorizonOrchestrator(
            registry=self.registry,
            tool_executor=self.tool_executor,
            audit_logger=self.audit,
        )

    async def test_scenario_f_secret_isolation_invariants(self) -> None:
        # --- 1. Synthetic secret is stored using the existing Loop 11 secure secret system ---
        self.assertTrue(self.vault.exists(self.secret_ref))
        with self.vault.access_secret(self.secret_ref, SecretAccessType.SECRET_USE) as val:
            self.assertEqual(val, self.raw_secret)

        # --- 2. Reasoning receives only an opaque reference if a reference is necessary ---
        goal_text = f"Create file sync_telemetry.txt with content 'Sync reference {self.secret_ref}'"
        goal = await self.orchestrator.submit_goal(goal_text)

        # Assemble plan step referencing only opaque ID
        step1 = TaskStep(
            step_id="step_sync_1",
            sequence=1,
            description=f"Call cloud sync with secret reference",
            tool_name="cloud.sync_data",
            arguments={"secret_ref": self.secret_ref},
            risk_level=ToolRiskLevel.LOW,
        )
        goal.task_plan.steps = [step1]

        executed_goal = await self.orchestrator.execute_goal(goal.goal_id)
        self.assertEqual(executed_goal.status, GoalStatus.COMPLETED)

        # --- 3. Verify Raw secret does NOT appear in Goal, Requirements, Plan, Steps, Metadata ---
        goal_serialized = executed_goal.model_dump_json()
        self.assertNotIn(self.raw_secret, goal_serialized)
        self.assertIn(self.secret_ref, goal_serialized)

        for req in executed_goal.requirements:
            self.assertNotIn(self.raw_secret, req.description)

        for step in executed_goal.task_plan.steps:
            self.assertNotIn(self.raw_secret, str(step.arguments))
            self.assertNotIn(self.raw_secret, str(step.result))

        self.assertNotIn(self.raw_secret, str(executed_goal.metadata))

        # --- 4. Verify Checkpoints reject secret material in snapshots ---
        # Valid safe snapshot succeeds
        safe_chk = Checkpoint(
            checkpoint_id="chk_safe_01",
            completed_step_ids=["step_sync_1"],
            state_snapshot={"active_reference": self.secret_ref, "count": 42},
        )
        self.assertEqual(safe_chk.state_snapshot["active_reference"], self.secret_ref)

        # Attempt to insert forbidden key into checkpoint raises validation error
        with self.assertRaises(ValueError):
            Checkpoint(
                checkpoint_id="chk_leak_01",
                completed_step_ids=["step_sync_1"],
                state_snapshot={"api_key": self.raw_secret},
            )

        with self.assertRaises(ValueError):
            Checkpoint(
                checkpoint_id="chk_leak_02",
                completed_step_ids=["step_sync_1"],
                state_snapshot={"secret_value": self.raw_secret},
            )

        # --- 5. Verify Memory records do NOT store raw plaintext secret ---
        self.vault.store_secret(
            identifier="BUDDY_MEMORY_ENCRYPTION_KEY",
            secret_value="synthetic_memory_key_passphrase_32_bytes_test!",
            metadata={"description": "Test memory key"},
        )
        cfg = BuddyConfig(memory_encryption_enabled=True)
        encryptor = get_memory_encryptor(cfg, vault_service=self.vault)
        mem_db = self.workspace / "memory.db"
        mem_store = SqliteMemoryStore(db_path=mem_db, encryptor=encryptor)
        mem_service = MemoryService(store=mem_store, config=cfg)
        mem_mgr = MemoryManager(service=mem_service, config=cfg)

        await mem_mgr.remember(
            content=f"Cloud telemetry task completed using secret ref {self.secret_ref}",
            memory_type=MemoryType.EPISODIC,
        )

        # Raw DB content must never contain the raw secret
        raw_db_bytes = mem_db.read_bytes()
        self.assertNotIn(self.raw_secret.encode("utf-8"), raw_db_bytes)

        # --- 6. Verify Normal tool output and scrubbing prevent leakage ---
        req_leak = ToolRequest(
            request_id="req_leak_1",
            tool_name="test.synthetic_leak_secret",
            arguments={"raise_exception": False},
        )
        res_leak = await self.tool_executor.execute(req_leak)
        self.assertTrue(res_leak.success)
        # Verify tool executor scrubbed raw secret from output dictionary
        self.assertNotIn(self.raw_secret, str(res_leak.output))
        self.assertEqual(res_leak.output["token"], REDACTED_SECRET)
        self.assertEqual(res_leak.output["api_key"], REDACTED_SECRET)

        # --- 7. Verify Exceptions do not leak secret material ---
        req_exc = ToolRequest(
            request_id="req_exc_1",
            tool_name="test.synthetic_leak_secret",
            arguments={"raise_exception": True},
        )
        res_exc = await self.tool_executor.execute(req_exc)
        self.assertFalse(res_exc.success)
        self.assertEqual(res_exc.status, ToolExecutionStatus.FAILED)
        # Redaction scrubs exception message
        self.assertNotIn(self.raw_secret, str(res_exc.error))

        # --- 8. Verify Audit logs contain zero occurrences of raw secret ---
        audit_text = self.audit_log.read_text(encoding="utf-8")
        self.assertNotIn(self.raw_secret, audit_text)

        # --- 9. Raw secret cannot be recovered through reasoning layer ---
        # The orchestrator and specialist reasoning modules only inspect goal/plan/ref
        self.assertNotIn(self.raw_secret, str(self.orchestrator._goals))

        # --- 10. Secret lifecycle remains controlled exclusively by Loop 11 ---
        # Rotation
        rotated_val = "synthetic-dummy-rotated-v2-strictly-test"
        rot_res = self.vault.rotate_secret(self.secret_ref, rotated_val)
        self.assertTrue(rot_res.success)
        self.assertEqual(rot_res.new_version, 2)

        # Deletion
        del_res = self.vault.delete_secret(self.secret_ref)
        self.assertTrue(del_res)
        self.assertFalse(self.vault.exists(self.secret_ref))

        # Audit log still clean
        audit_text_final = self.audit_log.read_text(encoding="utf-8")
        self.assertNotIn(self.raw_secret, audit_text_final)
        self.assertNotIn(rotated_val, audit_text_final)


if __name__ == "__main__":
    unittest.main()
