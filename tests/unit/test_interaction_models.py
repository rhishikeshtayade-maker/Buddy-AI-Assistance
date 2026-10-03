"""Unit tests for BUDDY Interaction Models and UIActionProposal."""

from __future__ import annotations

import unittest
from pydantic import ValidationError

from app.tools.interaction_models import (
    InteractionAction,
    InteractionRequest,
    MouseButton,
    TextSensitivity,
    UIActionProposal,
)
from app.tools.models import ToolRiskLevel
from app.vision.models import BoundingBox, VisionTarget


class TestInteractionModels(unittest.TestCase):
    """Test interaction enums, models, and proposal transformations."""

    def test_bounding_box_center_calculation(self) -> None:
        bbox = BoundingBox(x=100, y=200, width=50, height=30)
        self.assertEqual(bbox.center, (125, 215))
        self.assertEqual(bbox.as_tuple, (100, 200, 50, 30))

    def test_bounding_box_rejects_negative_or_zero_dimensions(self) -> None:
        with self.assertRaises(ValidationError):
            BoundingBox(x=-10, y=0, width=50, height=50)
        with self.assertRaises(ValidationError):
            BoundingBox(x=0, y=0, width=0, height=50)

    def test_vision_target_properties(self) -> None:
        target = VisionTarget(
            target_id="btn_submit",
            label="Submit Button",
            bounding_box=BoundingBox(x=400, y=300, width=80, height=40),
            confidence=0.98,
            screen_fingerprint="fp_abc123",
            screen_dimensions=(1920, 1080),
            category="SAFE",
        )
        self.assertEqual(target.center, (440, 320))
        self.assertTrue(target.is_verified)

    def test_ui_action_proposal_to_interaction_request(self) -> None:
        target = VisionTarget(
            target_id="btn_save",
            label="Save File",
            bounding_box=BoundingBox(x=50, y=60, width=100, height=40),
            screen_fingerprint="fp_screen_1",
            screen_dimensions=(1920, 1080),
        )
        proposal = UIActionProposal(
            action_type=InteractionAction.CLICK,
            target=target,
            screen_fingerprint="fp_screen_1",
            screen_dimensions=(1920, 1080),
            risk_level=ToolRiskLevel.MODERATE,
            reason="Save document changes",
        )
        req = proposal.to_interaction_request(conversation_id="conv_123")

        self.assertEqual(req.action_type, InteractionAction.CLICK)
        self.assertEqual(req.target_id, "btn_save")
        self.assertEqual(req.coordinates, (100.0, 80.0))  # center
        self.assertEqual(req.screen_fingerprint, "fp_screen_1")
        self.assertEqual(req.conversation_id, "conv_123")

    def test_ui_action_proposal_to_tool_request(self) -> None:
        target = VisionTarget(
            target_id="btn_save",
            label="Save File",
            bounding_box=BoundingBox(x=50, y=60, width=100, height=40),
            screen_fingerprint="fp_screen_1",
            screen_dimensions=(1920, 1080),
        )
        proposal = UIActionProposal(
            action_type=InteractionAction.CLICK,
            target=target,
            screen_fingerprint="fp_screen_1",
            screen_dimensions=(1920, 1080),
        )
        tool_req = proposal.to_tool_request()
        self.assertEqual(tool_req.tool_name, "mouse.click")
        self.assertEqual(tool_req.arguments["target_id"], "btn_save")
        self.assertEqual(tool_req.arguments["screen_fingerprint"], "fp_screen_1")

    def test_interaction_request_rejects_extra_fields(self) -> None:
        with self.assertRaises(ValidationError):
            InteractionRequest(
                action_type=InteractionAction.CLICK,
                unexpected_arbitrary_field="bypass_attempt",  # type: ignore
            )


if __name__ == "__main__":
    unittest.main()
