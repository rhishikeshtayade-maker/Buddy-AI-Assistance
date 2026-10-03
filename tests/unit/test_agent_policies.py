"""Unit tests for BUDDY Agent Execution Policies."""

from __future__ import annotations

import unittest

from app.agent.models import FailureCategory, RetryPolicy
from app.agent.policies import (
    classify_failure,
    contains_forbidden_arguments,
    is_forbidden_tool,
    should_replan,
    should_retry,
)
from app.tools.models import ToolExecutionStatus


class TestAgentPolicies(unittest.TestCase):
    """Test failure classification, retry boundaries, and forbidden tool detection."""

    def test_classify_failure_categories(self) -> None:
        self.assertEqual(
            classify_failure("SCREEN_CHANGED: visual fingerprint mismatch"),
            FailureCategory.SCREEN_CHANGED,
        )
        self.assertEqual(
            classify_failure("Target 'btn_submit' is not a registered, verified VisionTarget"),
            FailureCategory.TARGET_NOT_FOUND,
        )
        self.assertEqual(
            classify_failure(status=ToolExecutionStatus.CONFIRMATION_REQUIRED),
            FailureCategory.CONFIRMATION_REQUIRED,
        )
        self.assertEqual(
            classify_failure(status=ToolExecutionStatus.AUTHENTICATION_REQUIRED),
            FailureCategory.AUTHENTICATION_REQUIRED,
        )
        self.assertEqual(
            classify_failure(status=ToolExecutionStatus.TIMEOUT),
            FailureCategory.TOOL_TIMEOUT,
        )
        self.assertEqual(
            classify_failure("Interaction with protected application '1password' is strictly forbidden"),
            FailureCategory.SECURITY_BLOCKED,
        )
        self.assertEqual(
            classify_failure("Permission denied by security policy", status=ToolExecutionStatus.DENIED),
            FailureCategory.PERMISSION_DENIED,
        )

    def test_should_retry_boundaries(self) -> None:
        policy = RetryPolicy(max_retries=2)

        # Transient and screen changed are retryable within limit
        self.assertTrue(should_retry(FailureCategory.TRANSIENT, 0, policy))
        self.assertTrue(should_retry(FailureCategory.SCREEN_CHANGED, 1, policy))
        self.assertFalse(should_retry(FailureCategory.SCREEN_CHANGED, 2, policy))  # Exceeded limit

        # Non-retryable categories fail immediately
        self.assertFalse(should_retry(FailureCategory.PERMISSION_DENIED, 0, policy))
        self.assertFalse(should_retry(FailureCategory.AUTHENTICATION_REQUIRED, 0, policy))
        self.assertFalse(should_retry(FailureCategory.SECURITY_BLOCKED, 0, policy))
        self.assertFalse(should_retry(FailureCategory.INVALID_ARGUMENT, 0, policy))

    def test_should_replan_conditions(self) -> None:
        self.assertTrue(should_replan(FailureCategory.SCREEN_CHANGED, replan_count=0))
        self.assertTrue(should_replan(FailureCategory.TARGET_NOT_FOUND, replan_count=1))
        self.assertFalse(should_replan(FailureCategory.SCREEN_CHANGED, replan_count=3))  # Exceeded max replans

        # Non-replan categories
        self.assertFalse(should_replan(FailureCategory.PERMISSION_DENIED, replan_count=0))
        self.assertFalse(should_replan(FailureCategory.SECURITY_BLOCKED, replan_count=0))

    def test_forbidden_tool_detection(self) -> None:
        self.assertTrue(is_forbidden_tool("shell.execute"))
        self.assertTrue(is_forbidden_tool("python.eval"))
        self.assertTrue(is_forbidden_tool("powershell"))
        self.assertTrue(is_forbidden_tool("cmd"))
        self.assertFalse(is_forbidden_tool("app.open"))
        self.assertFalse(is_forbidden_tool("mouse.click"))

    def test_forbidden_argument_injection_detection(self) -> None:
        self.assertTrue(contains_forbidden_arguments({"cmd": "powershell.exe -c Get-Process"}))
        self.assertTrue(contains_forbidden_arguments({"code": "eval('import os')"}))
        self.assertTrue(contains_forbidden_arguments({"script": "subprocess.Popen()"}))
        self.assertFalse(contains_forbidden_arguments({"application": "notepad"}))
        self.assertFalse(contains_forbidden_arguments({"query": "monthly_report.txt"}))


if __name__ == "__main__":
    unittest.main()
