"""Unit tests for Failure Diagnostician (Loop 12)."""

import unittest
from app.agent.reasoning.diagnostics import FailureDiagnostician
from app.agent.reasoning.models import ReasoningFailureCategory


class TestDiagnostics(unittest.TestCase):
    def setUp(self):
        self.diagnostician = FailureDiagnostician()

    def test_security_block_diagnosis(self):
        diag = self.diagnostician.diagnose_failure(
            error_message="Action denied by policy: shell injection attempt",
            tool_name="system.cmd",
        )
        self.assertEqual(diag.category, ReasoningFailureCategory.SECURITY_BLOCK)
        self.assertFalse(diag.retryable)
        self.assertFalse(diag.replannable)
        self.assertTrue(diag.requires_user)
        self.assertEqual(diag.max_retries, 0)

    def test_target_not_found_diagnosis(self):
        diag = self.diagnostician.diagnose_failure(
            error_message="File 'report.csv' does not exist",
            tool_name="file.read",
        )
        self.assertEqual(diag.category, ReasoningFailureCategory.TARGET_NOT_FOUND)
        self.assertTrue(diag.retryable)
        self.assertTrue(diag.replannable)
        self.assertEqual(diag.max_retries, 2)

    def test_timeout_diagnosis(self):
        diag = self.diagnostician.diagnose_failure(
            error_message="Execution deadline exceeded (timeout)",
            tool_name="browser.navigate",
        )
        self.assertEqual(diag.category, ReasoningFailureCategory.TIMEOUT)
        self.assertTrue(diag.retryable)
        self.assertEqual(diag.max_retries, 1)


if __name__ == "__main__":
    unittest.main()
