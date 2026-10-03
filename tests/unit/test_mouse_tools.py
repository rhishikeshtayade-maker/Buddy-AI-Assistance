"""Unit tests for BUDDY Controlled Mouse Tools."""

from __future__ import annotations

import unittest

from app.security.interaction_policy import InteractionPolicy
from app.tools.interaction_models import MouseButton
from app.tools.mouse import (
    MockMouseController,
    MouseClickTool,
    MouseDoubleClickTool,
    MouseScrollTool,
)
from app.vision.models import BoundingBox, VisionTarget
from app.vision.screen import MockScreenManager


class TestMouseTools(unittest.IsolatedAsyncioTestCase):
    """Test mouse.click, mouse.double_click, and mouse.scroll tools."""

    async def asyncSetUp(self) -> None:
        self.screen_mgr = MockScreenManager()
        self.policy = InteractionPolicy(screen_manager=self.screen_mgr)
        self.mouse_ctrl = MockMouseController()

        self.target = VisionTarget(
            target_id="btn_ok",
            label="OK Button",
            bounding_box=BoundingBox(x=200, y=300, width=100, height=50),
            screen_fingerprint=self.screen_mgr.get_screen_fingerprint(),
            screen_dimensions=(1920, 1080),
        )
        self.policy.register_verified_target(self.target)

        self.click_tool = MouseClickTool(self.policy, self.mouse_ctrl, self.screen_mgr)
        self.double_click_tool = MouseDoubleClickTool(self.policy, self.mouse_ctrl, self.screen_mgr)
        self.scroll_tool = MouseScrollTool(self.policy, self.mouse_ctrl)

    async def test_mouse_click_execution_and_verify(self) -> None:
        args = {
            "target_id": "btn_ok",
            "screen_fingerprint": self.target.screen_fingerprint,
        }
        validated = await self.click_tool.validate_input(args)
        # Center of (200, 300, 100, 50) is (250, 325)
        self.assertEqual(validated["coordinates"], (250, 325))

        res = await self.click_tool.execute(validated)
        self.assertTrue(res["clicked"])
        self.assertEqual(res["coordinates"], [250, 325])
        self.assertTrue(await self.click_tool.verify(validated, res))

        # Check mock controller actions
        self.assertEqual(len(self.mouse_ctrl.actions), 1)
        self.assertEqual(self.mouse_ctrl.actions[0]["action"], "click")
        self.assertEqual(self.mouse_ctrl.actions[0]["x"], 250)
        self.assertEqual(self.mouse_ctrl.actions[0]["y"], 325)

    async def test_mouse_double_click_execution(self) -> None:
        args = {
            "target_id": "btn_ok",
            "screen_fingerprint": self.target.screen_fingerprint,
        }
        validated = await self.double_click_tool.validate_input(args)
        res = await self.double_click_tool.execute(validated)
        self.assertTrue(res["double_clicked"])
        self.assertTrue(await self.double_click_tool.verify(validated, res))

        self.assertEqual(len(self.mouse_ctrl.actions), 1)
        self.assertEqual(self.mouse_ctrl.actions[0]["action"], "double_click")

    async def test_mouse_scroll_execution(self) -> None:
        args = {"amount": 5}
        validated = await self.scroll_tool.validate_input(args)
        res = await self.scroll_tool.execute(validated)
        self.assertTrue(res["scrolled"])
        self.assertEqual(res["amount"], 5)
        self.assertTrue(await self.scroll_tool.verify(validated, res))

        self.assertEqual(len(self.mouse_ctrl.actions), 1)
        self.assertEqual(self.mouse_ctrl.actions[0]["amount"], 5)

    async def test_mouse_scroll_bounds_check(self) -> None:
        with self.assertRaises(ValueError):
            await self.scroll_tool.validate_input({"amount": 0})
        with self.assertRaises(ValueError):
            await self.scroll_tool.validate_input({"amount": 500})  # Exceeds max 100


if __name__ == "__main__":
    unittest.main()
