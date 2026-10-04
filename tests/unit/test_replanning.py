"""Unit tests for Safe Replanner (Loop 12)."""

import unittest
from app.agent.models import Task, TaskStep
from app.agent.reasoning.diagnostics import FailureDiagnostician
from app.agent.reasoning.evaluator import PlanQualityEvaluator
from app.agent.reasoning.models import FailureDiagnosis, Goal, ReasoningFailureCategory, TaskBudget
from app.agent.reasoning.replanner import SafeReplanner
from app.security.path_policy import PathPolicy
from app.tools.builtin import FileCreateTool, FileReadTool, FileSearchTool
from app.tools.registry import ToolRegistry


class TestReplanning(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        policy = PathPolicy()
        self.registry.register_tool(FileCreateTool(policy))
        self.registry.register_tool(FileReadTool(policy))
        self.registry.register_tool(FileSearchTool(policy))
        self.evaluator = PlanQualityEvaluator(self.registry)
        self.diagnostician = FailureDiagnostician()
        self.replanner = SafeReplanner(self.registry, self.evaluator, self.diagnostician)

    def test_replan_target_not_found(self):
        step = TaskStep(
            sequence=1,
            description="Read config",
            tool_name="file.read",
            arguments={"path": "config.json"},
        )
        task = Task(user_goal="Read config", steps=[step])
        diag = FailureDiagnosis(
            category=ReasoningFailureCategory.TARGET_NOT_FOUND,
            message="config.json not found",
            retryable=True,
            replannable=True,
        )

        success = self.replanner.replan_failed_step(task, step, diag)
        self.assertTrue(success)
        self.assertEqual(task.replan_count, 1)
        # Search step should have been inserted
        self.assertEqual(task.steps[0].tool_name, "file.search")

    def test_replan_rejected_on_security_block(self):
        step = TaskStep(sequence=1, description="Bad step", tool_name="file.read", arguments={})
        task = Task(user_goal="Bad", steps=[step])
        diag = FailureDiagnosis(
            category=ReasoningFailureCategory.SECURITY_BLOCK,
            message="Blocked by policy",
            retryable=False,
            replannable=False,
            requires_user=True,
        )

        success = self.replanner.replan_failed_step(task, step, diag)
        self.assertFalse(success)
        self.assertEqual(task.replan_count, 0)


if __name__ == "__main__":
    unittest.main()
