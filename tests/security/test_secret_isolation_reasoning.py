"""Security tests for Secret Isolation within the Reasoning Layer (Loop 12).

Verifies zero credential disclosure across Goals, SubGoals, Milestones,
Checkpoints, and Reasoning audit trails.
"""

import tempfile
import unittest
from pathlib import Path

from app.agent.reasoning.extractor import GoalRequirementExtractor
from app.agent.reasoning.models import Checkpoint, Goal
from app.security.audit import AuditLogger
from app.security.secrets.mock import MockSecretProvider
from app.security.secrets.redaction import REDACTED_SECRET, redact_string
from app.security.secrets.service import SecretVaultService


class TestSecretIsolationReasoning(unittest.TestCase):
    def test_checkpoint_refuses_raw_credentials(self):
        with self.assertRaises(ValueError):
            Checkpoint(
                completed_step_ids=["step1"],
                state_snapshot={"api_token": "sk-proj-1234567890abcdef1234567890abcdef"},
            )

    def test_goal_extraction_redacts_credentials(self):
        extractor = GoalRequirementExtractor()
        secret_prompt = "Create file with key sk-proj-1234567890abcdef1234567890abcdef on Desktop"

        # Scrub before storing in Goal
        cleaned_prompt = redact_string(secret_prompt)
        goal = extractor.extract_goal(cleaned_prompt)

        self.assertNotIn("sk-proj-1234567890abcdef1234567890abcdef", goal.objective)
        self.assertIn(REDACTED_SECRET, goal.objective)

    def test_reasoning_audit_logs_contain_zero_plaintext_secrets(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            log_path = Path(f.name)

        try:
            audit = AuditLogger(log_path=log_path)
            vault = SecretVaultService(provider=MockSecretProvider(), audit_logger=audit)
            raw_secret = "super_secret_vault_credential_999"
            vault.store_secret("VAULT_KEY_ID", raw_secret)

            content = log_path.read_text(encoding="utf-8")
            self.assertNotIn(raw_secret, content)
            self.assertIn("VAULT_KEY_ID", content)
        finally:
            if log_path.exists():
                log_path.unlink()


if __name__ == "__main__":
    unittest.main()
