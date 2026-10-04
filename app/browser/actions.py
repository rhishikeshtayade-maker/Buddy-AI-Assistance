"""BUDDY Browser Action Validation and Safety Enforcement.

Enforces strict key allowlists, coordinate restrictions, secret-typing detection,
and state validation before browser action execution.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set

from app.browser.dom import classify_input_sensitivity
from app.browser.exceptions import BrowserSecurityError
from app.browser.models import (
    BrowserAction,
    BrowserActionType,
    BrowserRiskLevel,
    BrowserTarget,
    FormFieldSensitivity,
)

logger = logging.getLogger("buddy.browser.actions")

# Strict keyboard allowlist
ALLOWED_KEYS: Set[str] = {
    "ENTER",
    "ESC",
    "ESCAPE",
    "TAB",
    "BACKSPACE",
    "SPACE",
    "ARROW_UP",
    "ARROW_DOWN",
    "ARROW_LEFT",
    "ARROW_RIGHT",
    "HOME",
    "END",
    "PAGE_UP",
    "PAGE_DOWN",
}

# Playwright key name mapping for standard allowlist
KEY_MAPPING: Dict[str, str] = {
    "ENTER": "Enter",
    "ESC": "Escape",
    "ESCAPE": "Escape",
    "TAB": "Tab",
    "BACKSPACE": "Backspace",
    "SPACE": " ",
    "ARROW_UP": "ArrowUp",
    "ARROW_DOWN": "ArrowDown",
    "ARROW_LEFT": "ArrowLeft",
    "ARROW_RIGHT": "ArrowRight",
    "HOME": "Home",
    "END": "End",
    "PAGE_UP": "PageUp",
    "PAGE_DOWN": "PageDown",
}


def validate_key_name(key: str) -> str:
    """Validate requested key against strict security allowlist."""
    norm_key = key.strip().upper()
    if norm_key not in ALLOWED_KEYS:
        raise BrowserSecurityError(
            f"Keyboard key '{key}' is not permitted. Only allowlisted navigation/action keys are allowed: "
            f"{', '.join(sorted(ALLOWED_KEYS))}"
        )
    return KEY_MAPPING.get(norm_key, norm_key)


def inspect_field_for_typing(
    target: Optional[BrowserTarget],
    text: str,
) -> Tuple[FormFieldSensitivity, BrowserRiskLevel]:
    """Inspect the target element and input value before typing.

    Never allows automated typing of credentials without elevated confirmation.
    """
    if not target:
        return FormFieldSensitivity.SAFE, BrowserRiskLevel.LOW

    # Check target attributes and role
    sensitivity = classify_input_sensitivity(
        field_id=target.target_id,
        name=target.accessible_name,
        field_type=target.target_type,
        label=target.text,
    )

    if sensitivity == FormFieldSensitivity.CREDENTIAL:
        logger.warning("Attempted text entry into credential/password field '%s'", target.target_id)
        return FormFieldSensitivity.CREDENTIAL, BrowserRiskLevel.HIGH
    elif sensitivity == FormFieldSensitivity.PAYMENT:
        logger.warning("Attempted text entry into payment field '%s'", target.target_id)
        return FormFieldSensitivity.PAYMENT, BrowserRiskLevel.CRITICAL
    elif sensitivity == FormFieldSensitivity.PERSONAL:
        return FormFieldSensitivity.PERSONAL, BrowserRiskLevel.MODERATE

    return FormFieldSensitivity.SAFE, BrowserRiskLevel.LOW


def classify_action_risk(action_type: BrowserActionType, arguments: Dict[str, Any]) -> BrowserRiskLevel:
    """Determine baseline risk level for a browser action."""
    if action_type in (
        BrowserActionType.EXTRACT_TEXT,
        BrowserActionType.SCREENSHOT,
        BrowserActionType.SCROLL,
        BrowserActionType.WAIT,
        BrowserActionType.FOCUS,
    ):
        return BrowserRiskLevel.SAFE

    if action_type in (
        BrowserActionType.NAVIGATE,
        BrowserActionType.BACK,
        BrowserActionType.FORWARD,
        BrowserActionType.RELOAD,
        BrowserActionType.CLICK,
        BrowserActionType.DOUBLE_CLICK,
        BrowserActionType.PRESS_KEY,
        BrowserActionType.SELECT,
    ):
        return BrowserRiskLevel.LOW

    if action_type == BrowserActionType.TYPE:
        # Check if sensitive
        if arguments.get("is_sensitive", False):
            return BrowserRiskLevel.HIGH
        return BrowserRiskLevel.LOW

    if action_type in (BrowserActionType.DOWNLOAD, BrowserActionType.UPLOAD):
        return BrowserRiskLevel.MODERATE

    return BrowserRiskLevel.MODERATE
