"""Unit tests for Plan Quality Evaluator (Loop 12)."""

import unittest
from app.agent.models import Task, TaskStep
from app.agent.reasoning.evaluator import PlanQualityEvaluator
from app.agent.reasoning.models import AutonomyLevel, StepEvaluationCategory
from app.security.path_policy import PathPolicy
from app.tools.builtin import FileCreateTool, FileReadTool
from app.tools.models import ToolExecutionStatus, ToolResult, ToolRiskLevel
from app.tools.registry import ToolRegistry


class TestPlanEvaluator(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        policy = PathPolicy()
        self.registry.register_tool(FileCreateTool(policy))
        self.registry.register_tool(FileReadTool(policy))
        self.evaluator = PlanQualityEvaluator(self.registry)

    def test_cycle_detection_in_dag(self):
        # Step 1 depends on Step 2, and Step 2 depends on Step 1
        s1 = TaskStep(step_id="s1", sequence=1, description="Step 1", tool_name="file.read", arguments={"path": "a.txt"}, dependencies=["s2"])
        s2 = TaskStep(step_id="s2", sequence=2, description="Step 2", tool_name="file.read", arguments={"path": "b.txt"}, dependencies=["s1"])

        task = Task(user_goal="Cyclic task", steps=[s1, s2])
        is_valid, issues = self.evaluator.evaluate_plan_quality(task)
        self.assertFalse(is_valid)
        self.assertTrue(any("Cyclic dependency" in issue for issue in issues))

    def test_unknown_tool_rejection(self):
        s1 = TaskStep(step_id="s1", sequence=1, description="Bad tool", tool_name="malicious.tool", arguments={})
        task = Task(user_goal="Unknown tool task", steps=[s1])
        is_valid, issues = self.evaluator.evaluate_plan_quality(task)
        self.assertFalse(is_valid)
        self.assertTrue(any("unregistered tool" in issue for issue in issues))

    def test_step_result_evaluation_success_and_failure(self):
        step = TaskStep(step_id="s1", sequence=1, description="Read", tool_name="file.read", arguments={"path": "a.txt"})

        success_res = ToolResult(
            request_id="r1", tool_name="file.read", success=True, verified=True, status=ToolExecutionStatus.SUCCEEDED
        )
        eval_succ = self.evaluator.evaluate_step_result(step, success_res)
        self.assertEqual(eval_succ.category, StepEvaluationCategory.SUCCESS)
        self.assertTrue(eval_succ.is_verified)

        fail_res = ToolResult(
            request_id="r2", tool_name="file.read", success=False, verified=False, status=ToolExecutionStatus.FAILED, error="File missing"
        )
        eval_fail = self.evaluator.evaluate_step_result(step, fail_res)
        self.assertEqual(eval_fail.category, StepEvaluationCategory.RECOVERABLE_FAILURE)
        self.assertFalse(eval_fail.is_verified)


if __name__ == "__main__":
    unittest.main()
