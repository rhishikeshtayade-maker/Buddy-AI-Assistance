"""BUDDY Controlled Interaction Policy.

Enforces coordinate bounds checking, verified target binding, screen fingerprint
freshness (stale-screen rejection), dangerous action categorization, sensitive text rejection,
and protected application boundaries.
"""

from __future__ import annotations

import logging
import math
import re
import time
from typing import Dict, List, Optional, Set, Tuple

from app.core.exceptions import SecurityError
from app.tools.interaction_models import (
    InteractionAction,
    InteractionRequest,
    TextSensitivity,
)
from app.tools.models import ToolRiskLevel
from app.vision.models import VisionTarget
from app.vision.screen import ScreenManager

logger = logging.getLogger("buddy.security.interaction")

# Allowlisted non-alphanumeric keyboard keys
ALLOWED_KEYS: Set[str] = {
    "ENTER", "ESC", "TAB", "BACKSPACE", "SPACE",
    "ARROW_UP", "ARROW_DOWN", "ARROW_LEFT", "ARROW_RIGHT",
    "HOME", "END", "PAGE_UP", "PAGE_DOWN",
}

# Known valid display identifiers
KNOWN_DISPLAYS: Set[str] = {
    "primary", "main", "0", "display_0", "display_1", "screen_0",
}

# Protected applications that BUDDY is strictly forbidden from automating
PROTECTED_APPLICATIONS: Set[str] = {
    "1password",
    "bitwarden",
    "keepass",
    "lastpass",
    "credential manager",
    "windows security",
    "security dashboard",
    "uac",
    "user account control",
}

# Sensitive text keywords indicating password or credential typing
SENSITIVE_TEXT_PATTERNS = [
    re.compile(r"(?i)(password|passphrase|secret|api[_-]?key|token|pin|otp|credential)"),
    re.compile(r"(?i)(sk-[a-zA-Z0-9_\-]{10,})"),
]

# Action risk classifications based on target semantic intent
DANGEROUS_ACTION_KEYWORDS: Set[str] = {
    "delete", "uninstall", "format", "erase", "remove", "drop", "destroy", "kill",
}

CRITICAL_ACTION_KEYWORDS: Set[str] = {
    "security", "credential", "privilege", "sudo", "admin", "firewall", "registry",
}

SAFE_ACTION_KEYWORDS: Set[str] = {
    "search", "navigate", "open menu", "view", "help",
}


class InteractionSecurityError(SecurityError):
    """Raised when an interaction proposal or request violates security policies."""


class InteractionPolicy:
    """Policy engine enforcing strict boundaries on mouse and keyboard execution."""

    def __init__(
        self,
        screen_manager: Optional[ScreenManager] = None,
        target_ttl_seconds: float = 30.0,
        min_confidence_threshold: float = 0.70,
    ) -> None:
        self._screen_manager = screen_manager
        self._target_ttl = target_ttl_seconds
        self._min_confidence = min_confidence_threshold
        self._verified_targets: Dict[str, VisionTarget] = {}

    def register_verified_target(self, target: VisionTarget) -> None:
        """Register an empirically located VisionTarget for the active screen session."""
        self._verified_targets[target.target_id] = target
        logger.debug("Registered verified target: %s ('%s')", target.target_id, target.label)

    def get_verified_target(self, target_id: str) -> Optional[VisionTarget]:
        return self._verified_targets.get(target_id)

    def clear_targets(self) -> None:
        """Clear targets (e.g. upon major window/screen state navigation)."""
        self._verified_targets.clear()

    def validate_coordinates(
        self,
        x: float,
        y: float,
        screen_dimensions: Tuple[int, int],
    ) -> Tuple[int, int]:
        """Assert coordinates are finite, non-negative, and strictly within screen bounds."""
        if not (math.isfinite(x) and math.isfinite(y)):
            raise InteractionSecurityError(f"Coordinates must be finite numeric values, got ({x}, {y}).")

        width, height = screen_dimensions
        if x < 0 or y < 0:
            raise InteractionSecurityError(f"Negative coordinates are forbidden: ({x}, {y}).")

        if x >= width or y >= height:
            raise InteractionSecurityError(
                f"Coordinates ({x}, {y}) out of display bounds (screen: {width}x{height})."
            )

        return (int(round(x)), int(round(y)))

    def validate_key(self, key_name: str) -> str:
        """Assert key name is present in the safe keyboard allowlist."""
        normalized = key_name.strip().upper()
        if normalized not in ALLOWED_KEYS:
            raise InteractionSecurityError(
                f"Keyboard key '{key_name}' is not in the allowed keys list: {sorted(ALLOWED_KEYS)}."
            )
        return normalized

    def classify_text_sensitivity(self, text: str) -> TextSensitivity:
        """Determine if text contains sensitive secrets or passwords."""
        for pattern in SENSITIVE_TEXT_PATTERNS:
            if pattern.search(text):
                return TextSensitivity.SENSITIVE_TEXT
        return TextSensitivity.NORMAL_TEXT

    def evaluate_target_risk(self, target: VisionTarget) -> ToolRiskLevel:
        """Determine risk tier from target category and label."""
        label_lower = target.label.lower()
        category_upper = target.category.upper()

        if category_upper == "CRITICAL" or any(kw in label_lower for kw in CRITICAL_ACTION_KEYWORDS):
            return ToolRiskLevel.CRITICAL
        if category_upper == "DANGEROUS" or any(kw in label_lower for kw in DANGEROUS_ACTION_KEYWORDS):
            return ToolRiskLevel.HIGH
        if category_upper == "SAFE" or any(kw in label_lower for kw in SAFE_ACTION_KEYWORDS):
            return ToolRiskLevel.LOW
        # Default for UI actions like click is MODERATE (requires confirmation)
        return ToolRiskLevel.MODERATE

    def validate_request(
        self,
        request: InteractionRequest,
        current_screen_manager: Optional[ScreenManager] = None,
    ) -> Tuple[int, int]:
        """Validate an InteractionRequest across all security gates.

        Returns:
            Validated integer (x, y) coordinates for mouse actions, or (0, 0) for keyboard/scroll.

        Raises:
            InteractionSecurityError: If any security invariant fails.
        """
        sm = current_screen_manager or self._screen_manager

        # 1. Protected Applications Check
        target_app = request.metadata.get("application", "").lower()
        for protected in PROTECTED_APPLICATIONS:
            if protected in target_app:
                raise InteractionSecurityError(
                    f"Interaction with protected application '{target_app}' is strictly forbidden."
                )

        # 2. Display Bounds & Identifier Check
        if request.screen_id and request.screen_id not in KNOWN_DISPLAYS:
            raise InteractionSecurityError(f"Unknown or unsupported display '{request.screen_id}'.")

        # 3. Direct Mouse Movement Check (Phase 4: never expose arbitrary mouse movement)
        if request.action_type == InteractionAction.MOVE:
            raise InteractionSecurityError("Arbitrary mouse movement is not exposed as a direct action.")

        # 4. Scroll Validation
        if request.action_type == InteractionAction.SCROLL:
            if request.amount is None or request.amount == 0:
                raise InteractionSecurityError("Scroll action requires non-zero 'amount' parameter.")
            if abs(request.amount) > 100:
                raise InteractionSecurityError("Scroll amount exceeds safe limits (-100 to 100).")
            return (0, 0)

        # 5. Keyboard Validation
        if request.action_type == InteractionAction.KEY_PRESS:
            if not request.key:
                raise InteractionSecurityError("Key press action requires 'key' parameter.")
            self.validate_key(request.key)
            return (0, 0)

        if request.action_type == InteractionAction.TYPE:
            if not request.text:
                raise InteractionSecurityError("Type action requires non-empty 'text' parameter.")
            sensitivity = self.classify_text_sensitivity(request.text)
            if sensitivity == TextSensitivity.SENSITIVE_TEXT:
                raise InteractionSecurityError(
                    "Automated typing of passwords, credentials, tokens, or OTPs is strictly forbidden."
                )
            return (0, 0)

        # 6. Mouse Operations: Target Binding Requirement
        if not request.target_id:
            raise InteractionSecurityError(
                "Direct coordinate injection rejected: Interaction request MUST reference a verified target_id."
            )

        target = self.get_verified_target(request.target_id)
        if not target:
            raise InteractionSecurityError(
                f"Target '{request.target_id}' is not a registered, verified VisionTarget."
            )

        # 7. Target Verification, Confidence, Ambiguity, and Expiration Checks
        if not target.is_verified:
            raise InteractionSecurityError(f"Target '{request.target_id}' is not verified.")

        if target.confidence < self._min_confidence:
            raise InteractionSecurityError(
                f"Target '{request.target_id}' confidence {target.confidence:.2f} is below "
                f"minimum required threshold ({self._min_confidence:.2f})."
            )

        if target.metadata.get("ambiguous", False):
            raise InteractionSecurityError(
                f"Target '{request.target_id}' is flagged as ambiguous. A distinct, single target is required."
            )

        target_age = time.time() - target.timestamp
        if target_age > self._target_ttl:
            raise InteractionSecurityError(
                f"Target '{request.target_id}' has expired (detected {target_age:.1f}s ago, max TTL {self._target_ttl}s). "
                "Request a fresh screen analysis."
            )

        # 8. Target / Request Fingerprint Match
        if request.screen_fingerprint and request.screen_fingerprint != target.screen_fingerprint:
            raise InteractionSecurityError(
                f"Screen fingerprint mismatch: request fingerprint '{request.screen_fingerprint}' "
                f"does not match target detection fingerprint '{target.screen_fingerprint}'."
            )

        # 9. Screen Dimensions & Bounds Checking
        dims = request.screen_dimensions
        if not dims and sm:
            dims = sm.get_screen_dimensions()
        dims = dims or target.screen_dimensions or (1920, 1080)

        raw_coords = request.coordinates or (float(target.center[0]), float(target.center[1]))
        coords = self.validate_coordinates(raw_coords[0], raw_coords[1], dims)

        # 10. Stale-Screen Protection (Fingerprint Verification)
        if sm:
            current_fp = sm.get_screen_fingerprint()
            expected_fp = request.screen_fingerprint or target.screen_fingerprint
            if expected_fp and current_fp != expected_fp:
                raise InteractionSecurityError(
                    f"SCREEN_CHANGED: Current screen fingerprint '{current_fp}' does not match "
                    f"target detection fingerprint '{expected_fp}'. Action rejected to prevent mis-clicks."
                )

        return coords
