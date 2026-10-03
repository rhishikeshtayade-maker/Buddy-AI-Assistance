"""Unit tests for BUDDY Agent Models."""

from __future__ import annotations

import unittest
from pydantic import ValidationError

from app.agent.models import (
    FailureCategory,
    RetryPolicy,
    StepStatus,
    Task,
    TaskResult,
    TaskStatus,
    TaskStep,
)
from app.tools.models import ToolRiskLevel


class TestAgentModels(unittest.TestCase):
    """Test Task, TaskStep, and TaskResult models."""

    def test_task_step_initialization_defaults(self) -> None:
        step = TaskStep(
            sequence=1,
            description="Open Notepad application",
            tool_name="app.open",
            arguments={"application": "notepad"},
        )
        self.assertEqual(step.sequence, 1)
        self.assertEqual(step.status, StepStatus.PENDING)
        self.assertEqual(step.risk_level, ToolRiskLevel.LOW)
        self.assertFalse(step.requires_confirmation)
        self.assertFalse(step.requires_authentication)
        self.assertEqual(step.dependencies, [])
        self.assertEqual(step.retry_policy.max_retries, 2)

    def test_task_step_rejects_extra_fields(self) -> None:
        with self.assertRaises(ValidationError):
            TaskStep(
                sequence=1,
                description="Invalid step",
                tool_name="app.open",
                unexpected_field="injection_attempt",  # type: ignore
            )

    def test_task_step_navigation_and_lookup(self) -> None:
        step1 = TaskStep(
            step_id="step_01",
            sequence=1,
            description="Step 1",
            tool_name="app.open",
            arguments={"application": "notepad"},
        )
        step2 = TaskStep(
            step_id="step_02",
            sequence=2,
            description="Step 2",
            tool_name="keyboard.type_text",
            arguments={"text": "hello"},
            dependencies=["step_01"],
        )

        task = Task(
            task_id="task_test_01",
            user_goal="Open Notepad and type hello",
            steps=[step1, step2],
        )

        self.assertEqual(task.status, TaskStatus.PENDING)
        self.assertEqual(task.current_step.step_id, "step_01")
        self.assertEqual(task.get_step_by_id("step_02").description, "Step 2")
        self.assertIsNone(task.get_step_by_id("nonexistent"))

        task.current_step_index = 1
        self.assertEqual(task.current_step.step_id, "step_02")

        task.current_step_index = 2
        self.assertIsNone(task.current_step)

    def test_retry_policy_defaults_and_immutability(self) -> None:
        policy = RetryPolicy()
        self.assertEqual(policy.max_retries, 2)
        self.assertIn(FailureCategory.TRANSIENT, policy.retryable_categories)
        self.assertIn(FailureCategory.SCREEN_CHANGED, policy.retryable_categories)
        self.assertNotIn(FailureCategory.PERMISSION_DENIED, policy.retryable_categories)

    def test_task_result_summary(self) -> None:
        res = TaskResult(
            task_id="task_res_01",
            status=TaskStatus.COMPLETED,
            completed_steps=["step_01", "step_02"],
            final_message="All steps completed and verified.",
            verified=True,
            execution_latency=1.25,
            tool_calls_count=2,
        )
        self.assertTrue(res.verified)
        self.assertEqual(len(res.completed_steps), 2)
        self.assertEqual(res.tool_calls_count, 2)


if __name__ == "__main__":
    unittest.main()
