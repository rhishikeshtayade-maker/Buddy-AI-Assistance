"""Unit tests for BUDDY Agent TaskExecutor."""

from __future__ import annotations

import unittest

from app.agent.executor import TaskExecutor
from app.agent.models import (
    FailureCategory,
    RetryPolicy,
    StepStatus,
    Task,
    TaskStatus,
    TaskStep,
)
from app.core.events import EventBus
from app.security.confirmation import ConfirmationManager
from app.security.interaction_policy import InteractionPolicy
from app.tools.builtin import register_builtin_tools
from app.tools.executor import ToolExecutor
from app.tools.mouse import MockMouseController, MouseClickTool
from app.tools.registry import ToolRegistry
from app.vision.models import BoundingBox, VisionTarget
from app.vision.screen import MockScreenManager


class TestAgentExecutor(unittest.IsolatedAsyncioTestCase):
    """Test sequential execution, dependency checks, confirmation gating, and cancellation."""

    async def asyncSetUp(self) -> None:
        self.screen_mgr = MockScreenManager(dimensions=(1920, 1080), initial_fingerprint="fp_screen_init")
        self.policy = InteractionPolicy(screen_manager=self.screen_mgr)
        self.mouse_ctrl = MockMouseController()

        self.registry = ToolRegistry()
        register_builtin_tools(self.registry, interaction_policy=self.policy)
        self.registry.unregister_tool("mouse.click")
        self.registry.register_tool(MouseClickTool(self.policy, self.mouse_ctrl, self.screen_mgr))

        target = VisionTarget(
            target_id="btn_confirm_test",
            label="Confirm Button",
            bounding_box=BoundingBox(x=10, y=10, width=50, height=20),
            screen_fingerprint="fp_screen_init",
        )
        self.policy.register_verified_target(target)

        self.conf_mgr = ConfirmationManager(default_ttl_seconds=30.0)
        self.event_bus = EventBus()
        self.tool_executor = ToolExecutor(
            registry=self.registry,
            confirmation_manager=self.conf_mgr,
            event_bus=self.event_bus,
        )
        self.executor = TaskExecutor(
            tool_executor=self.tool_executor,
            event_bus=self.event_bus,
        )

    async def asyncTearDown(self) -> None:
        await self.event_bus.shutdown()

    async def test_successful_multi_step_sequence(self) -> None:
        step1 = TaskStep(
            step_id="s1",
            sequence=1,
            description="Get system info",
            tool_name="system.get_info",
            arguments={},
        )
        step2 = TaskStep(
            step_id="s2",
            sequence=2,
            description="Get battery info",
            tool_name="system.get_battery",
            arguments={},
            dependencies=["s1"],
        )
        task = Task(user_goal="Check system diagnostics", steps=[step1, step2])

        result = await self.executor.execute_task(task)
        self.assertEqual(result.status, TaskStatus.COMPLETED)
        self.assertTrue(result.verified)
        self.assertEqual(result.completed_steps, ["s1", "s2"])
        self.assertEqual(step1.status, StepStatus.SUCCEEDED)
        self.assertEqual(step2.status, StepStatus.SUCCEEDED)

    async def test_failed_step_halts_subsequent_execution(self) -> None:
        # Step 1 asks to read a nonexistent file -> will fail
        step1 = TaskStep(
            step_id="s1",
            sequence=1,
            description="Read non-existent file",
            tool_name="file.read",
            arguments={"path": "Documents/definitely_nonexistent_file_xyz_123.txt"},
            retry_policy=RetryPolicy(max_retries=0),
        )
        step2 = TaskStep(
            step_id="s2",
            sequence=2,
            description="Get battery",
            tool_name="system.get_battery",
            arguments={},
            dependencies=["s1"],
        )
        task = Task(user_goal="Read file and check battery", steps=[step1, step2])

        result = await self.executor.execute_task(task)
        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertFalse(result.verified)
        self.assertEqual(step1.status, StepStatus.FAILED)
        self.assertEqual(step2.status, StepStatus.PENDING)

    async def test_dependency_failure_skips_dependent_step(self) -> None:
        step1 = TaskStep(
            step_id="s1",
            sequence=1,
            description="Step 1 that fails",
            tool_name="file.read",
            arguments={"path": "Documents/missing_file.txt"},
            retry_policy=RetryPolicy(max_retries=0),
        )
        step2 = TaskStep(
            step_id="s2",
            sequence=2,
            description="Step 2 depending on s1",
            tool_name="system.get_battery",
            dependencies=["s1"],
        )
        task = Task(user_goal="Dep check", steps=[step1, step2])

        # Execute step 1 to failure manually
        step1.status = StepStatus.FAILED
        task.current_step_index = 1  # Point to step 2

        # Step 2 dependency s1 is FAILED -> s2 must be SKIPPED
        result = await self.executor.execute_task(task)
        self.assertEqual(step2.status, StepStatus.SKIPPED)
        self.assertEqual(step2.failure_category, FailureCategory.DEPENDENCY_FAILED)

    async def test_confirmation_required_pauses_task(self) -> None:
        # mouse.click requires confirmation
        step = TaskStep(
            step_id="s_click",
            sequence=1,
            description="Click button requiring confirmation",
            tool_name="mouse.click",
            arguments={"target_id": "btn_confirm_test", "screen_fingerprint": "fp_screen_init"},
        )
        task = Task(user_goal="Click confirm button", steps=[step])

        # First run: no confirmation token provided -> task pauses in WAITING_CONFIRMATION
        result = await self.executor.execute_task(task)
        self.assertEqual(result.status, TaskStatus.WAITING_CONFIRMATION)
        self.assertEqual(task.status, TaskStatus.WAITING_CONFIRMATION)
        token = result.metadata.get("confirmation_token")
        self.assertTrue(len(token) > 0)

        # Second run: provide token -> executes and succeeds
        resumed_result = await self.executor.execute_task(task, confirmation_token=token)
        self.assertEqual(resumed_result.status, TaskStatus.COMPLETED)
        self.assertEqual(step.status, StepStatus.SUCCEEDED)

    async def test_human_cancellation_aborts_task(self) -> None:
        step1 = TaskStep(
            step_id="s1",
            sequence=1,
            description="Get info",
            tool_name="system.get_info",
        )
        step2 = TaskStep(
            step_id="s2",
            sequence=2,
            description="Get battery",
            tool_name="system.get_battery",
        )
        task = Task(user_goal="Multi-step goal", steps=[step1, step2])

        # Cancel task before execution
        self.executor.cancel_task(task, reason="User clicked stop")
        result = await self.executor.execute_task(task)

        self.assertEqual(result.status, TaskStatus.CANCELLED)
        self.assertIn("cancelled", result.final_message.lower())
        self.assertEqual(step1.status, StepStatus.PENDING)
        self.assertEqual(step2.status, StepStatus.PENDING)


if __name__ == "__main__":
    unittest.main()
