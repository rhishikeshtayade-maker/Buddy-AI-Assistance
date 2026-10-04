"""BUDDY Failure Diagnosis and Classification Subsystem (Loop 12).

Analyzes tool errors, exceptions, and verification failures to produce structured,
actionable diagnostics with strict bounds on retries and replanning.
"""

from __future__ import annotations

import re
from typing import Optional

from app.agent.reasoning.models import (
    FailureDiagnosis,
    ReasoningFailureCategory,
)
from app.tools.models import ToolResult


class FailureDiagnostician:
    """Diagnoses failure causes and returns bounded recovery advice."""

    def diagnose_failure(
        self,
        error_message: str,
        tool_name: Optional[str] = None,
        tool_result: Optional[ToolResult] = None,
    ) -> FailureDiagnosis:
        err = (error_message or "").lower()

        # 1. Security block (never retryable, never replannable without user)
        if any(w in err for w in ["security", "prohibited", "forbidden", "denied by policy", "injection"]):
            return FailureDiagnosis(
                category=ReasoningFailureCategory.SECURITY_BLOCK,
                message=f"Action blocked by BUDDY security policy: {error_message}",
                retryable=False,
                replannable=False,
                requires_user=True,
                max_retries=0,
                suggested_fix="Do not attempt prohibited action.",
            )

        # 2. Permission denied / ungranted capability
        if "permission" in err or (tool_result and tool_result.status.value == "DENIED"):
            return FailureDiagnosis(
                category=ReasoningFailureCategory.PERMISSION_DENIED,
                message=f"Permission denied for '{tool_name}': {error_message}",
                retryable=False,
                replannable=False,
                requires_user=True,
                max_retries=0,
                suggested_fix="Request explicit user permission grant.",
            )

        # 3. Authentication / Confirmation required
        if (
            (tool_result and tool_result.status.value in ("CONFIRMATION_REQUIRED", "AUTHENTICATION_REQUIRED"))
            or any(w in err for w in ["confirm", "confirmation", "auth", "login", "credentials", "unauthorized", "401"])
        ):
            return FailureDiagnosis(
                category=ReasoningFailureCategory.AUTH_REQUIRED,
                message=f"User confirmation or authentication required for '{tool_name}': {error_message}",
                retryable=False,
                replannable=False,
                requires_user=True,
                max_retries=0,
                suggested_fix="Prompt user for confirmation token or credentials.",
            )

        # 4. Target not found / File not found / Element not found
        if any(w in err for w in ["not found", "does not exist", "nosuchfile", "missing"]):
            return FailureDiagnosis(
                category=ReasoningFailureCategory.TARGET_NOT_FOUND,
                message=f"Target resource was not found: {error_message}",
                retryable=True,
                replannable=True,
                requires_user=False,
                max_retries=2,
                suggested_fix="Check path / query or replan alternative path.",
            )

        # 5. Timeout
        if any(w in err for w in ["timeout", "timed out", "deadline"]):
            return FailureDiagnosis(
                category=ReasoningFailureCategory.TIMEOUT,
                message=f"Operation timed out: {error_message}",
                retryable=True,
                replannable=True,
                requires_user=False,
                max_retries=1,
                suggested_fix="Retry once with increased bounded wait or alternative tool.",
            )

        # 6. Network failure
        if any(w in err for w in ["network", "connection", "connect", "dns", "unreachable"]):
            return FailureDiagnosis(
                category=ReasoningFailureCategory.NETWORK_FAILURE,
                message=f"Network error encountered: {error_message}",
                retryable=True,
                replannable=False,
                requires_user=False,
                max_retries=2,
                suggested_fix="Check network connectivity or retry after delay.",
            )

        # 7. Ambiguous state
        if "ambiguous" in err or "multiple" in err:
            return FailureDiagnosis(
                category=ReasoningFailureCategory.AMBIGUOUS_STATE,
                message=f"Ambiguous state encountered: {error_message}",
                retryable=False,
                replannable=True,
                requires_user=True,
                max_retries=0,
                suggested_fix="Seek user clarification on target disambiguation.",
            )

        # 8. User cancelled
        if "cancel" in err:
            return FailureDiagnosis(
                category=ReasoningFailureCategory.USER_CANCELLED,
                message="Operation was cancelled by user.",
                retryable=False,
                replannable=False,
                requires_user=False,
                max_retries=0,
            )

        # 9. Generic tool failure
        return FailureDiagnosis(
            category=ReasoningFailureCategory.TOOL_FAILURE,
            message=f"Tool '{tool_name or 'unknown'}' failed: {error_message}",
            retryable=True,
            replannable=True,
            requires_user=False,
            max_retries=1,
            suggested_fix="Inspect arguments and retry or replan step.",
        )
