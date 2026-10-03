"""End-to-End Tests for BUDDY Controlled Mouse and Keyboard Interaction.

Verifies the 5 Phase 17 deterministic scenarios:
Test 1: User "Click Save" -> screen analyzed -> Save identified -> confirmation required -> confirmed -> click executed -> verified.
Test 2: AI supplies x=500, y=500 without verified target -> REJECTED. No click.
Test 3: Target found on screen A, screen changes to screen B -> SCREEN_CHANGED. No click.
Test 4: AI requests "Type my password" -> REJECTED. No keyboard interaction.
Test 5: AI requests "Delete this file" -> Dangerous policy + confirmation boundary. No action without authorization.
"""

from __future__ import annotations

import unittest

from app.ai.conversation import ConversationManager
from app.ai.models import MessageRole
from app.ai.provider import MockAIProvider
from app.ai.router import AIRouter
from app.core import BuddyConfig, BuddyState, EventBus, StateMachine
from app.security.confirmation import ConfirmationManager
from app.security.interaction_policy import InteractionPolicy
from app.security.permissions import PermissionEngine
from app.tools.executor import ToolExecutor
from app.tools.interaction_models import (
    InteractionAction,
    UIActionProposal,
)
from app.tools.keyboard import MockKeyboardController, TypeTextTool
from app.tools.models import ToolRequest, ToolRiskLevel
from app.tools.mouse import MockMouseController, MouseClickTool
from app.tools.registry import ToolRegistry
from app.vision.models import BoundingBox, VisionTarget
from app.vision.screen import MockScreenManager


class TestInteractionE2E(unittest.IsolatedAsyncioTestCase):
    """End-to-end tests verifying AI -> Proposal -> Permission -> Confirmation -> Interaction -> Verification."""

    async def asyncSetUp(self) -> None:
        self.config = BuddyConfig(
            app_env="testing",
            ai_provider="mock",
            tools_enabled=True,
        )
        self.event_bus = EventBus()
        self.state_machine = StateMachine(BuddyState.IDLE)
        self.screen_mgr = MockScreenManager(dimensions=(1920, 1080), initial_fingerprint="fp_screen_init")
        self.policy = InteractionPolicy(screen_manager=self.screen_mgr)
        self.mouse_ctrl = MockMouseController()
        self.kbd_ctrl = MockKeyboardController()

        # Register verified targets
        self.save_target = VisionTarget(
            target_id="btn_save_01",
            label="Save Button",
            bounding_box=BoundingBox(x=100, y=200, width=80, height=40),
            screen_fingerprint="fp_screen_init",
            screen_dimensions=(1920, 1080),
            category="MODERATE",
        )
        self.policy.register_verified_target(self.save_target)

        self.delete_target = VisionTarget(
            target_id="btn_delete_01",
            label="Delete File Button",
            bounding_box=BoundingBox(x=500, y=600, width=100, height=40),
            screen_fingerprint="fp_screen_init",
            screen_dimensions=(1920, 1080),
            category="DANGEROUS",
        )
        self.policy.register_verified_target(self.delete_target)

        self.registry = ToolRegistry()
        self.click_tool = MouseClickTool(self.policy, self.mouse_ctrl, self.screen_mgr)
        self.type_tool = TypeTextTool(self.policy, self.kbd_ctrl)
        self.registry.register_tool(self.click_tool)
        self.registry.register_tool(self.type_tool)

        self.conf_mgr = ConfirmationManager(default_ttl_seconds=30.0)
        self.perm_engine = PermissionEngine(interaction_policy=self.policy)
        self.executor = ToolExecutor(
            registry=self.registry,
            permission_engine=self.perm_engine,
            confirmation_manager=self.conf_mgr,
            event_bus=self.event_bus,
        )

        self.mock_ai = MockAIProvider()
        self.router = AIRouter(self.config)
        self.router.register_provider("mock", self.mock_ai)

        self.conv_mgr = ConversationManager(
            config=self.config,
            event_bus=self.event_bus,
            state_machine=self.state_machine,
            router=self.router,
            tool_executor=self.executor,
        )

    async def asyncTearDown(self) -> None:
        await self.event_bus.shutdown()

    async def test_end_to_end_click_save_with_confirmation_flow(self) -> None:
        """PHASE 17 TEST 1:
        User requests click Save -> AI proposes tool call -> Confirmation required ->
        User confirms with token -> Execution & verification -> Success.
        """
        # 1. AI queues tool call for mouse.click with verified target_id
        self.mock_ai.set_next_tool_calls([{
            "id": "call_save_action_01",
            "tool_name": "mouse.click",
            "arguments": {
                "target_id": "btn_save_01",
                "screen_fingerprint": "fp_screen_init",
            },
        }])

        # First turn: AI responds that confirmation is required
        response = await self.conv_mgr.process_user_turn("Click the Save button.")
        self.assertIn("confirmation", response.content.lower())
        self.assertEqual(len(self.mouse_ctrl.actions), 0)

        # Retrieve issued token from conversation tool result message
        tool_msgs = [m for m in self.conv_mgr.history if m.role == MessageRole.TOOL]
        self.assertEqual(len(tool_msgs), 1)
        self.assertIn("confirmation_required", tool_msgs[0].content)

        # Find the pending confirmation token from ConfirmationManager
        tokens = list(self.conf_mgr._tokens.keys())
        self.assertTrue(len(tokens) > 0)
        token = tokens[0]

        # 2. Second turn: User confirms with token
        self.mock_ai.set_next_tool_calls([{
            "id": "call_save_action_01",
            "tool_name": "mouse.click",
            "arguments": {
                "target_id": "btn_save_01",
                "screen_fingerprint": "fp_screen_init",
            },
        }])

        confirm_response = await self.conv_mgr.process_user_turn(
            "Yes, proceed.",
            confirmation_token=token,
        )

        # Must report action completed and verified
        self.assertIn("verified", confirm_response.content.lower())
        self.assertEqual(len(self.mouse_ctrl.actions), 1)
        self.assertEqual(self.mouse_ctrl.actions[0]["action"], "click")
        # Center of (100, 200, 80, 40) is (140, 220)
        self.assertEqual(self.mouse_ctrl.actions[0]["x"], 140)
        self.assertEqual(self.mouse_ctrl.actions[0]["y"], 220)

    async def test_end_to_end_raw_coordinate_injection_rejected(self) -> None:
        """PHASE 17 TEST 2:
        AI tries to send raw coordinates without a verified target -> must be rejected.
        """
        self.mock_ai.set_next_tool_calls([{
            "tool_name": "mouse.click",
            "arguments": {
                "x": 500,
                "y": 500,
            },
        }])

        response = await self.conv_mgr.process_user_turn("Click at 500, 500")
        self.assertIn("could not complete", response.content.lower())
        self.assertEqual(len(self.mouse_ctrl.actions), 0)

    async def test_end_to_end_stale_screen_rejects_action(self) -> None:
        """PHASE 17 TEST 3:
        Screen changed after target detection -> action rejected with SCREEN_CHANGED.
        """
        self.screen_mgr.simulate_screen_change("fp_screen_changed_v99")
        self.mock_ai.set_next_tool_calls([{
            "tool_name": "mouse.click",
            "arguments": {
                "target_id": "btn_save_01",
                "screen_fingerprint": "fp_screen_init",  # Old fingerprint
            },
        }])

        response = await self.conv_mgr.process_user_turn("Click Save")
        self.assertIn("could not complete", response.content.lower())
        self.assertEqual(len(self.mouse_ctrl.actions), 0)

    async def test_end_to_end_password_typing_rejected(self) -> None:
        """PHASE 17 TEST 4:
        AI requests to type a password -> rejected.
        """
        self.mock_ai.set_next_tool_calls([{
            "tool_name": "keyboard.type_text",
            "arguments": {
                "text": "MySecretPassword123!",
            },
        }])

        response = await self.conv_mgr.process_user_turn("Type my password")
        self.assertIn("could not complete", response.content.lower())
        self.assertEqual(len(self.kbd_ctrl.typed_strings), 0)

    async def test_end_to_end_dangerous_delete_requires_authorization(self) -> None:
        """PHASE 17 TEST 5:
        AI requests: "Delete this file." -> dangerous policy + confirmation boundary.
        No action without explicit user confirmation.
        """
        # Target btn_delete_01 is registered as DANGEROUS
        self.assertEqual(self.policy.evaluate_target_risk(self.delete_target), ToolRiskLevel.HIGH)

        self.mock_ai.set_next_tool_calls([{
            "id": "call_delete_01",
            "tool_name": "mouse.click",
            "arguments": {
                "target_id": "btn_delete_01",
                "screen_fingerprint": "fp_screen_init",
            },
        }])

        # 1. First turn: user says "Delete this file"
        response = await self.conv_mgr.process_user_turn("Delete this file.")
        self.assertIn("confirmation", response.content.lower())
        # Zero clicks executed so far
        self.assertEqual(len(self.mouse_ctrl.actions), 0)

        # Token was issued
        tokens = list(self.conf_mgr._tokens.keys())
        self.assertTrue(len(tokens) > 0)
        token = tokens[0]

        # 2. Second turn: User confirms
        self.mock_ai.set_next_tool_calls([{
            "id": "call_delete_01",
            "tool_name": "mouse.click",
            "arguments": {
                "target_id": "btn_delete_01",
                "screen_fingerprint": "fp_screen_init",
            },
        }])

        confirm_response = await self.conv_mgr.process_user_turn(
            "Yes, I confirm deletion.",
            confirmation_token=token,
        )

        self.assertIn("verified", confirm_response.content.lower())
        self.assertEqual(len(self.mouse_ctrl.actions), 1)
        self.assertEqual(self.mouse_ctrl.actions[0]["action"], "click")
        # Center of (500, 600, 100, 40) is (550, 620)
        self.assertEqual(self.mouse_ctrl.actions[0]["x"], 550)
        self.assertEqual(self.mouse_ctrl.actions[0]["y"], 620)


if __name__ == "__main__":
    unittest.main()
