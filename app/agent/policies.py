"""BUDDY Agent Execution Policies and Failure Classifier.

Enforces retry limits, failure categorization, re-planning triggers,
and prohibited execution patterns.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from app.agent.models import FailureCategory, RetryPolicy
from app.tools.models import ToolExecutionStatus

logger = logging.getLogger("buddy.agent.policies")

# Strictly forbidden tools and aliases that can never be planned or executed
FORBIDDEN_TOOL_NAMES: Set[str] = {
    "shell.execute",
    "shell.run",
    "terminal.run",
    "python.eval",
    "python.exec",
    "system.shell",
    "system.bash",
    "system.powershell",
    "system.cmd",
    "powershell",
    "cmd",
    "bash",
    "sh",
    "exec",
    "eval",
}

# Forbidden keywords in tool arguments that suggest raw shell / code injection
FORBIDDEN_ARGUMENT_PATTERNS: Set[str] = {
    "cmd.exe",
    "powershell.exe",
    "powershell -c",
    "powershell -enc",
    "powershell",
    "pwsh",
    "bash -c",
    "eval(",
    "exec(",
    "__import__",
    "subprocess.",
    "os.system",
}

# Categories that are categorically non-retryable (fail closed immediately)
NON_RETRYABLE_CATEGORIES: Set[FailureCategory] = {
    FailureCategory.PERMISSION_DENIED,
    FailureCategory.CONFIRMATION_REQUIRED,
    FailureCategory.AUTHENTICATION_REQUIRED,
    FailureCategory.SECURITY_BLOCKED,
    FailureCategory.INVALID_ARGUMENT,
    FailureCategory.DEPENDENCY_FAILED,
}


def classify_failure(
    error: Optional[str] = None,
    status: Optional[ToolExecutionStatus] = None,
    details: Optional[Dict[str, Any]] = None,
) -> FailureCategory:
    """Categorize an error or status into a structured FailureCategory."""
    err_text = (error or "").lower()

    if status == ToolExecutionStatus.CONFIRMATION_REQUIRED or "confirmation" in err_text:
        return FailureCategory.CONFIRMATION_REQUIRED

    if status == ToolExecutionStatus.AUTHENTICATION_REQUIRED or "authentication" in err_text:
        return FailureCategory.AUTHENTICATION_REQUIRED

    if "screen_changed" in err_text or "fingerprint" in err_text:
        return FailureCategory.SCREEN_CHANGED

    if "target" in err_text and ("not found" in err_text or "not a registered" in err_text):
        return FailureCategory.TARGET_NOT_FOUND

    if status == ToolExecutionStatus.TIMEOUT or "timed out" in err_text:
        return FailureCategory.TOOL_TIMEOUT

    if status == ToolExecutionStatus.VERIFICATION_FAILED or "verification" in err_text:
        return FailureCategory.VERIFICATION_FAILED

    if "permission" in err_text or status == ToolExecutionStatus.DENIED:
        return FailureCategory.PERMISSION_DENIED

    if "protected application" in err_text or "strictly forbidden" in err_text or "security" in err_text:
        return FailureCategory.SECURITY_BLOCKED

    if "invalid" in err_text or "validation" in err_text or "schema" in err_text:
        return FailureCategory.INVALID_ARGUMENT

    if "transient" in err_text:
        return FailureCategory.TRANSIENT

    return FailureCategory.UNKNOWN


def should_retry(
    category: FailureCategory,
    retries_attempted: int,
    retry_policy: Optional[RetryPolicy] = None,
) -> bool:
    """Determine whether a step failure is eligible for a bounded retry."""
    policy = retry_policy or RetryPolicy()

    if category in NON_RETRYABLE_CATEGORIES:
        return False

    if retries_attempted >= policy.max_retries:
        return False

    return category in policy.retryable_categories


def should_replan(category: FailureCategory, replan_count: int, max_replans: int = 3) -> bool:
    """Determine whether dynamic environment change justifies re-planning."""
    if replan_count >= max_replans:
        return False

    return category in {
        FailureCategory.SCREEN_CHANGED,
        FailureCategory.TARGET_NOT_FOUND,
        FailureCategory.VERIFICATION_FAILED,
    }


def is_forbidden_tool(tool_name: str) -> bool:
    """Check if tool name is an unauthorized, dangerous, or raw shell tool."""
    normalized = tool_name.strip().lower()
    return normalized in FORBIDDEN_TOOL_NAMES


def contains_forbidden_arguments(arguments: Dict[str, Any]) -> bool:
    """Detect raw shell or python code injection within arguments."""
    arg_str = str(arguments).lower()
    return any(pattern.lower() in arg_str for pattern in FORBIDDEN_ARGUMENT_PATTERNS)
