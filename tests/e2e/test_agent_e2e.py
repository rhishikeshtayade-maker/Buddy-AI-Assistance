"""End-to-End Tests for BUDDY Agent Multi-Step Task Execution.

Verifies:
- Phase 24: "Open Notepad, type BUDDY TEST, and finish."
  End-to-end multi-step flow with per-step permission, confirmation gating, and verification.
- Phase 25: "Open Notepad, click text area, then click a nonexistent button."
  Failure scenario: first steps succeed, missing target fails, bounded recovery attempted,
  task stops honestly with verified=False without falsely claiming success.
"""

from __future__ import annotations

import unittest

from app.agent.executor import TaskExecutor
from app.agent.models import FailureCategory, StepStatus, Task, TaskStatus, TaskStep
from app.agent.planner import TaskPlanner
from app.agent.service import AgentService
from app.agent.validator import TaskPlanValidator
from app.ai.provider import MockAIProvider
from app.core.events import EventBus
from app.core.state import BuddyState, StateMachine
from app.security.confirmation import ConfirmationManager
from app.security.interaction_policy import InteractionPolicy
from app.security.permissions import PermissionEngine
from app.tools.builtin import register_builtin_tools
from app.tools.executor import ToolExecutor
from app.tools.keyboard import MockKeyboardController, TypeTextTool
from app.tools.mouse import MockMouseController, MouseClickTool
from app.tools.registry import ToolRegistry
from app.vision.models import BoundingBox, VisionTarget
from app.vision.screen import MockScreenManager


class TestAgentE2E(unittest.IsolatedAsyncioTestCase):
    """End-to-end tests verifying multi-step planning, gating, execution, and verification."""

    async def asyncSetUp(self) -> None:
        self.screen_mgr = MockScreenManager(dimensions=(1920, 1080), initial_fingerprint="fp_screen_init")
        self.policy = InteractionPolicy(screen_manager=self.screen_mgr)
        self.mouse_ctrl = MockMouseController()
        self.kbd_ctrl = MockKeyboardController()

        # Register verified targets
        self.notepad_target = VisionTarget(
            target_id="notepad_textarea",
            label="Notepad Editor",
            bounding_box=BoundingBox(x=200, y=200, width=400, height=300),
            screen_fingerprint="fp_screen_init",
            screen_dimensions=(1920, 1080),
            category="SAFE",
        )
        self.policy.register_verified_target(self.notepad_target)

        self.registry = ToolRegistry()
        register_builtin_tools(self.registry, interaction_policy=self.policy)

        # Replace mouse and keyboard with mock controllers for deterministic headless testing
        self.registry.unregister_tool("mouse.click")
        self.registry.unregister_tool("keyboard.type_text")
        click_tool = MouseClickTool(self.policy, self.mouse_ctrl, self.screen_mgr)
        type_tool = TypeTextTool(self.policy, self.kbd_ctrl)
        self.registry.register_tool(click_tool)
        self.registry.register_tool(type_tool)

        self.conf_mgr = ConfirmationManager(default_ttl_seconds=30.0)
        self.perm_engine = PermissionEngine(interaction_policy=self.policy)
        self.event_bus = EventBus()
        self.state_machine = StateMachine(BuddyState.IDLE)

        self.tool_executor = ToolExecutor(
            registry=self.registry,
            permission_engine=self.perm_engine,
            confirmation_manager=self.conf_mgr,
            event_bus=self.event_bus,
        )

        self.mock_ai = MockAIProvider()
        self.service = AgentService(
            registry=self.registry,
            tool_executor=self.tool_executor,
            ai_provider=self.mock_ai,
            event_bus=self.event_bus,
            state_machine=self.state_machine,
        )

    async def asyncTearDown(self) -> None:
        await self.event_bus.shutdown()

    async def test_phase24_multi_step_notepad_and_typing_task(self) -> None:
        """PHASE 24 REAL MULTI-STEP TASK:
        User: "Open Notepad, type BUDDY TEST, and finish."
        Expected:
        1. Planner decomposes goal into 3 steps: app.open -> mouse.click -> keyboard.type_text.
        2. Validator accepts.
        3. Step 1 (app.open) executes and succeeds.
        4. Step 2 (mouse.click) requires confirmation token -> paused in WAITING_CONFIRMATION.
        5. User confirms with token -> Step 2 executes, clicks (400, 350) and verifies.
        6. Step 3 (keyboard.type_text) executes, types 'BUDDY TEST', verifies character count.
        7. Task completes with COMPLETED status and verified=True.
        """
        # Step 1: Submit and start task
        first_result = await self.service.execute_goal("Open Notepad, type BUDDY TEST, and finish.")

        # Step 2 requires confirmation for mouse click
        self.assertEqual(first_result.status, TaskStatus.WAITING_CONFIRMATION)
        token = first_result.metadata.get("confirmation_token")
        self.assertTrue(len(token) > 0)

        # Retrieve active task
        task = self.service.get_task(first_result.task_id)
        self.assertIsNotNone(task)
        self.assertEqual(len(task.steps), 3)
        self.assertEqual(task.steps[0].status, StepStatus.SUCCEEDED)

        # Step 2: Resume with valid confirmation token
        final_result = await self.service.resume_task(task.task_id, confirmation_token=token)

        self.assertEqual(final_result.status, TaskStatus.COMPLETED)
        self.assertTrue(final_result.verified)
        self.assertEqual(len(final_result.completed_steps), 3)

        # Verify mouse and keyboard actions were dispatched
        self.assertEqual(len(self.mouse_ctrl.actions), 1)
        self.assertEqual(self.mouse_ctrl.actions[0]["action"], "click")
        # Center of (200, 200, 400, 300) is (400, 350)
        self.assertEqual(self.mouse_ctrl.actions[0]["x"], 400)
        self.assertEqual(self.mouse_ctrl.actions[0]["y"], 350)

        self.assertEqual(len(self.kbd_ctrl.typed_strings), 1)
        self.assertEqual(self.kbd_ctrl.typed_strings[0], "BUDDY TEST")

    async def test_phase25_failure_e2e_nonexistent_target_stops_honestly(self) -> None:
        """PHASE 25 FAILURE E2E:
        User: "Open Notepad, click the text area, then click a nonexistent button."
        Expected:
        - First step succeeds.
        - Nonexistent target fails.
        - Bounded recovery/re-plan attempted.
        - If target remains unavailable, task stops with FAILED status and verified=False.
        - BUDDY does NOT falsely claim success.
        """
        # Create a task with a valid first step and a missing target step
        step1 = TaskStep(
            step_id="s1",
            sequence=1,
            description="Open notepad",
            tool_name="app.open",
            arguments={"application": "notepad"},
        )
        step2 = TaskStep(
            step_id="s2",
            sequence=2,
            description="Click a nonexistent button",
            tool_name="mouse.click",
            arguments={"target_id": "nonexistent_ghost_button_99"},
            dependencies=["s1"],
        )
        task = Task(user_goal="Click nonexistent target", steps=[step1, step2], max_replans=1)

        result = await self.service.executor.execute_task(task)

        # Must terminate in FAILED status, never claiming success
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertFalse(result.verified)
        self.assertEqual(result.failed_step, "s2")
        self.assertIn("s1", result.completed_steps)
        self.assertNotIn("s2", result.completed_steps)
        self.assertIn("not a registered", result.final_message.lower())


if __name__ == "__main__":
    unittest.main()
