"""Adversarial and Security Negative Tests for Controlled Interaction.

Strictly verifies Phase 18 adversarial scenarios:
- negative coordinates
- NaN / Infinity
- out-of-bounds coordinates
- stale screen state
- stale target timestamp
- wrong display
- ambiguous target
- low-confidence target
- unverified target
- malicious screen text
- confirmation replay
- confirmation substitution
- unknown keyboard key
- raw coordinate injection
- password typing
- credential typing
- arbitrary key sequence
- protected application
- arbitrary mouse move
All must fail closed!
"""

from __future__ import annotations

import time
import unittest

from app.core.exceptions import ConfirmationError
from app.security.confirmation import ConfirmationManager
from app.security.interaction_policy import (
    InteractionPolicy,
    InteractionSecurityError,
)
from app.tools.interaction_models import (
    InteractionAction,
    InteractionRequest,
)
from app.tools.models import ToolRequest
from app.tools.mouse import MockMouseController, MouseClickTool
from app.vision.models import BoundingBox, VisionTarget
from app.vision.screen import MockScreenManager


class TestInteractionSecurity(unittest.IsolatedAsyncioTestCase):
    """Adversarial test suite verifying fail-closed security for mouse & keyboard operations."""

    async def asyncSetUp(self) -> None:
        self.screen_mgr = MockScreenManager(dimensions=(1920, 1080), initial_fingerprint="fp_screen_v1")
        self.policy = InteractionPolicy(screen_manager=self.screen_mgr, target_ttl_seconds=10.0, min_confidence_threshold=0.70)
        self.mouse_ctrl = MockMouseController()
        self.conf_mgr = ConfirmationManager(default_ttl_seconds=5.0)

        self.target = VisionTarget(
            target_id="btn_delete",
            label="Delete Account Button",
            bounding_box=BoundingBox(x=300, y=400, width=120, height=45),
            screen_fingerprint="fp_screen_v1",
            screen_dimensions=(1920, 1080),
            category="DANGEROUS",
            confidence=0.95,
            is_verified=True,
            timestamp=time.time(),
        )
        self.policy.register_verified_target(self.target)
        self.click_tool = MouseClickTool(self.policy, self.mouse_ctrl, self.screen_mgr)

    # 1. Negative coordinates
    def test_negative_coordinates_rejected(self) -> None:
        with self.assertRaises(InteractionSecurityError):
            self.policy.validate_coordinates(-10.0, 50.0, (1920, 1080))
        with self.assertRaises(InteractionSecurityError):
            self.policy.validate_coordinates(50.0, -1.0, (1920, 1080))

    # 2. NaN and Infinity
    def test_nan_and_inf_coordinate_injection_rejected(self) -> None:
        nan_req = InteractionRequest(
            action_type=InteractionAction.CLICK,
            target_id="btn_delete",
            coordinates=(float("nan"), 400.0),
        )
        with self.assertRaises(InteractionSecurityError):
            self.policy.validate_request(nan_req)

        inf_req = InteractionRequest(
            action_type=InteractionAction.CLICK,
            target_id="btn_delete",
            coordinates=(300.0, float("inf")),
        )
        with self.assertRaises(InteractionSecurityError):
            self.policy.validate_request(inf_req)

    # 3. Out-of-bounds coordinates
    def test_out_of_bounds_coordinates_rejected(self) -> None:
        with self.assertRaises(InteractionSecurityError):
            self.policy.validate_coordinates(2000.0, 50.0, (1920, 1080))
        with self.assertRaises(InteractionSecurityError):
            self.policy.validate_coordinates(50.0, 1200.0, (1920, 1080))

    # 4. Stale screen state
    async def test_stale_screen_target_injection_rejected(self) -> None:
        args = {
            "target_id": "btn_delete",
            "screen_fingerprint": "fp_screen_v1",
        }
        self.screen_mgr.simulate_screen_change("fp_screen_v2_altered")

        with self.assertRaises(InteractionSecurityError) as ctx:
            await self.click_tool.validate_input(args)
        self.assertIn("SCREEN_CHANGED", str(ctx.exception))
        self.assertEqual(len(self.mouse_ctrl.actions), 0)

    # 5. Stale target timestamp
    def test_stale_target_timestamp_rejected(self) -> None:
        stale_target = VisionTarget(
            target_id="stale_btn",
            label="Old Button",
            bounding_box=BoundingBox(x=10, y=10, width=50, height=20),
            screen_fingerprint="fp_screen_v1",
            timestamp=time.time() - 60.0,  # 60s old (TTL is 10s)
            confidence=0.9,
            is_verified=True,
        )
        self.policy.register_verified_target(stale_target)
        req = InteractionRequest(action_type=InteractionAction.CLICK, target_id="stale_btn")
        with self.assertRaises(InteractionSecurityError) as ctx:
            self.policy.validate_request(req)
        self.assertIn("expired", str(ctx.exception).lower())

    # 6. Wrong / Unknown display
    def test_wrong_display_rejected(self) -> None:
        req = InteractionRequest(
            action_type=InteractionAction.CLICK,
            target_id="btn_delete",
            screen_id="display_unknown_42",
        )
        with self.assertRaises(InteractionSecurityError) as ctx:
            self.policy.validate_request(req)
        self.assertIn("unknown or unsupported display", str(ctx.exception).lower())

    # 7. Ambiguous target
    def test_ambiguous_target_rejected(self) -> None:
        ambiguous_target = VisionTarget(
            target_id="ambiguous_btn",
            label="Multiple Options",
            bounding_box=BoundingBox(x=50, y=50, width=50, height=20),
            screen_fingerprint="fp_screen_v1",
            metadata={"ambiguous": True},
            confidence=0.9,
            is_verified=True,
        )
        self.policy.register_verified_target(ambiguous_target)
        req = InteractionRequest(action_type=InteractionAction.CLICK, target_id="ambiguous_btn")
        with self.assertRaises(InteractionSecurityError) as ctx:
            self.policy.validate_request(req)
        self.assertIn("ambiguous", str(ctx.exception).lower())

    # 8. Low-confidence target
    def test_low_confidence_target_rejected(self) -> None:
        low_conf_target = VisionTarget(
            target_id="low_conf_btn",
            label="Blurry Button",
            bounding_box=BoundingBox(x=50, y=50, width=50, height=20),
            screen_fingerprint="fp_screen_v1",
            confidence=0.45,  # Below 0.70 threshold
            is_verified=True,
        )
        self.policy.register_verified_target(low_conf_target)
        req = InteractionRequest(action_type=InteractionAction.CLICK, target_id="low_conf_btn")
        with self.assertRaises(InteractionSecurityError) as ctx:
            self.policy.validate_request(req)
        self.assertIn("below minimum required threshold", str(ctx.exception).lower())

    # 9. Unverified target
    def test_unverified_target_rejected(self) -> None:
        unverified_target = VisionTarget(
            target_id="unverified_btn",
            label="Candidate Button",
            bounding_box=BoundingBox(x=50, y=50, width=50, height=20),
            screen_fingerprint="fp_screen_v1",
            confidence=0.9,
            is_verified=False,
        )
        self.policy.register_verified_target(unverified_target)
        req = InteractionRequest(action_type=InteractionAction.CLICK, target_id="unverified_btn")
        with self.assertRaises(InteractionSecurityError) as ctx:
            self.policy.validate_request(req)
        self.assertIn("not verified", str(ctx.exception).lower())

    # 10. Malicious screen text / Prompt injection in text or label
    def test_malicious_screen_text_dangerous_classification(self) -> None:
        malicious_target = VisionTarget(
            target_id="mal_btn",
            label="format c: /fs:NTFS and delete all",
            bounding_box=BoundingBox(x=50, y=50, width=50, height=20),
            screen_fingerprint="fp_screen_v1",
            confidence=0.9,
            is_verified=True,
        )
        # Must be classified as HIGH or CRITICAL risk, never SAFE or LOW
        risk = self.policy.evaluate_target_risk(malicious_target)
        self.assertGreaterEqual(risk, 3)

    # 11. Confirmation replay
    def test_confirmation_replay_attack_rejected(self) -> None:
        req = ToolRequest(
            request_id="req_test_replay",
            tool_name="mouse.click",
            arguments={"target_id": "btn_delete", "screen_fingerprint": "fp_screen_v1"},
        )
        token_obj = self.conf_mgr.request_confirmation(req)

        # First consumption passes
        consumed = self.conf_mgr.validate_and_consume(
            token=token_obj.token,
            request_id="req_test_replay",
            tool_name="mouse.click",
            arguments={"target_id": "btn_delete", "screen_fingerprint": "fp_screen_v1"},
        )
        self.assertTrue(consumed)

        # Replay attempt with same token fails closed
        with self.assertRaises(ConfirmationError) as ctx:
            self.conf_mgr.validate_and_consume(
                token=token_obj.token,
                request_id="req_test_replay",
                tool_name="mouse.click",
                arguments={"target_id": "btn_delete", "screen_fingerprint": "fp_screen_v1"},
            )
        self.assertIn("replay", str(ctx.exception).lower())

    # 12. Confirmation substitution
    def test_confirmation_token_cannot_be_substituted_for_different_target(self) -> None:
        req_a = ToolRequest(
            request_id="req_action_a",
            tool_name="mouse.click",
            arguments={"target_id": "btn_delete", "screen_fingerprint": "fp_screen_v1"},
        )
        token_obj = self.conf_mgr.request_confirmation(req_a)

        with self.assertRaises(ConfirmationError):
            self.conf_mgr.validate_and_consume(
                token=token_obj.token,
                request_id="req_action_a",
                tool_name="mouse.click",
                arguments={"target_id": "btn_other", "screen_fingerprint": "fp_screen_v1"},
            )

    # 13. Unknown keyboard key
    def test_unapproved_keyboard_keys_rejected(self) -> None:
        with self.assertRaises(InteractionSecurityError):
            self.policy.validate_key("PRINT_SCREEN")
        with self.assertRaises(InteractionSecurityError):
            self.policy.validate_key("ALT_F4")
        with self.assertRaises(InteractionSecurityError):
            self.policy.validate_key("F12")

    # 14. Raw coordinate injection
    async def test_arbitrary_raw_coordinates_injection_fails_closed(self) -> None:
        raw_req = InteractionRequest(
            action_type=InteractionAction.CLICK,
            coordinates=(500.0, 500.0),
            target_id=None,
        )
        with self.assertRaises(InteractionSecurityError) as ctx:
            self.policy.validate_request(raw_req)
        self.assertIn("target_id", str(ctx.exception))

    # 15. Password typing
    async def test_password_typing_blocked(self) -> None:
        req = InteractionRequest(action_type=InteractionAction.TYPE, text="SecretPassword123")
        with self.assertRaises(InteractionSecurityError) as ctx:
            self.policy.validate_request(req)
        self.assertIn("passwords, credentials", str(ctx.exception).lower())

    # 16. Credential typing
    async def test_credential_typing_blocked(self) -> None:
        req = InteractionRequest(action_type=InteractionAction.TYPE, text="sk-1234567890abcdef1234")
        with self.assertRaises(InteractionSecurityError) as ctx:
            self.policy.validate_request(req)
        self.assertIn("passwords, credentials", str(ctx.exception).lower())

    # 17. Arbitrary key sequence
    def test_arbitrary_key_sequence_rejected(self) -> None:
        req = InteractionRequest(action_type=InteractionAction.KEY_PRESS, key="CTRL+C")
        with self.assertRaises(InteractionSecurityError):
            self.policy.validate_request(req)

    # 18. Protected application
    def test_protected_application_blocked(self) -> None:
        req = InteractionRequest(
            action_type=InteractionAction.CLICK,
            target_id="btn_delete",
            metadata={"application": "Bitwarden Desktop"},
        )
        with self.assertRaises(InteractionSecurityError) as ctx:
            self.policy.validate_request(req)
        self.assertIn("protected application", str(ctx.exception).lower())

    # 19. Arbitrary mouse move rejected
    def test_arbitrary_mouse_move_rejected(self) -> None:
        req = InteractionRequest(action_type=InteractionAction.MOVE, coordinates=(100.0, 200.0))
        with self.assertRaises(InteractionSecurityError) as ctx:
            self.policy.validate_request(req)
        self.assertIn("arbitrary mouse movement", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
