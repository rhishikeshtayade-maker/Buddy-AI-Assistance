"""Unit tests for BUDDY Interaction Policy."""

from __future__ import annotations

import unittest

from app.security.interaction_policy import (
    ALLOWED_KEYS,
    InteractionPolicy,
    InteractionSecurityError,
)
from app.tools.interaction_models import (
    InteractionAction,
    InteractionRequest,
    TextSensitivity,
)
from app.tools.models import ToolRiskLevel
from app.vision.models import BoundingBox, VisionTarget
from app.vision.screen import MockScreenManager


class TestInteractionPolicy(unittest.TestCase):
    """Test policy rules: coordinates, keys, text classification, and target binding."""

    def setUp(self) -> None:
        self.screen_mgr = MockScreenManager(dimensions=(1920, 1080), initial_fingerprint="fp_test_1")
        self.policy = InteractionPolicy(screen_manager=self.screen_mgr)
        self.target = VisionTarget(
            target_id="target_001",
            label="OK Button",
            bounding_box=BoundingBox(x=100, y=200, width=80, height=40),
            screen_fingerprint="fp_test_1",
            screen_dimensions=(1920, 1080),
            category="SAFE",
        )
        self.policy.register_verified_target(self.target)

    def test_coordinate_validation_finite_and_bounded(self) -> None:
        # Valid coordinates
        x, y = self.policy.validate_coordinates(500.4, 600.2, (1920, 1080))
        self.assertEqual((x, y), (500, 600))

        # Negative coordinates rejected
        with self.assertRaises(InteractionSecurityError):
            self.policy.validate_coordinates(-1.0, 500.0, (1920, 1080))

        # Out-of-bounds coordinates rejected
        with self.assertRaises(InteractionSecurityError):
            self.policy.validate_coordinates(1920.0, 500.0, (1920, 1080))
        with self.assertRaises(InteractionSecurityError):
            self.policy.validate_coordinates(500.0, 1080.0, (1920, 1080))

        # NaN / Infinity rejected
        with self.assertRaises(InteractionSecurityError):
            self.policy.validate_coordinates(float("nan"), 500.0, (1920, 1080))
        with self.assertRaises(InteractionSecurityError):
            self.policy.validate_coordinates(500.0, float("inf"), (1920, 1080))

    def test_key_validation_allowlist(self) -> None:
        for k in ["ENTER", "TAB", "ESC", "SPACE", "ARROW_DOWN"]:
            self.assertEqual(self.policy.validate_key(k), k)

        for bad_k in ["F13", "WIN", "SUPER", "CTRL_ALT_DEL", "PRINT_SCREEN"]:
            with self.assertRaises(InteractionSecurityError):
                self.policy.validate_key(bad_k)

    def test_text_sensitivity_classification(self) -> None:
        # Normal text
        self.assertEqual(
            self.policy.classify_text_sensitivity("Hello, this is a normal note."),
            TextSensitivity.NORMAL_TEXT,
        )

        # Sensitive credentials / passwords
        sensitive_samples = [
            "My password is P@ssw0rd123",
            "Please enter your OTP: 123456",
            "Here is the secret pin 9988",
            "sk-1234567890abcdef123456",
        ]
        for s in sensitive_samples:
            self.assertEqual(
                self.policy.classify_text_sensitivity(s),
                TextSensitivity.SENSITIVE_TEXT,
            )

    def test_rejection_of_raw_coordinate_injection_without_target(self) -> None:
        # Request with raw coordinates but missing target_id must be rejected
        raw_req = InteractionRequest(
            action_type=InteractionAction.CLICK,
            coordinates=(500.0, 300.0),
            target_id=None,
        )
        with self.assertRaises(InteractionSecurityError) as ctx:
            self.policy.validate_request(raw_req)
        self.assertIn("target_id", str(ctx.exception))

    def test_stale_screen_protection(self) -> None:
        valid_req = InteractionRequest(
            action_type=InteractionAction.CLICK,
            target_id="target_001",
            screen_fingerprint="fp_test_1",
        )
        # Screen is at fp_test_1 -> passes
        self.policy.validate_request(valid_req)

        # Screen changes to fp_test_2
        self.screen_mgr.simulate_screen_change("fp_test_2")

        # Stale request must now be rejected with SCREEN_CHANGED
        with self.assertRaises(InteractionSecurityError) as ctx:
            self.policy.validate_request(valid_req)
        self.assertIn("SCREEN_CHANGED", str(ctx.exception))

    def test_protected_application_blocked(self) -> None:
        req = InteractionRequest(
            action_type=InteractionAction.CLICK,
            target_id="target_001",
            screen_fingerprint="fp_test_1",
            metadata={"application": "1Password Vault"},
        )
        with self.assertRaises(InteractionSecurityError) as ctx:
            self.policy.validate_request(req)
        self.assertIn("protected application", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
