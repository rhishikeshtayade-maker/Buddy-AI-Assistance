"""Security tests for Autonomy Level Boundaries (Loop 12).

Verifies that autonomy levels restrict tool execution and never override
mandatory human confirmation for dangerous or destructive operations.
"""

import unittest
from app.agent.models import Task, TaskStep
from app.agent.reasoning.evaluator import PlanQualityEvaluator
from app.agent.reasoning.models import AutonomyLevel
from app.security.path_policy import PathPolicy
from app.tools.builtin import FileCreateTool, FileReadTool
from app.tools.models import ToolRiskLevel
from app.tools.registry import ToolRegistry


class TestAutonomySecurity(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        policy = PathPolicy()
        self.registry.register_tool(FileCreateTool(policy))  # LOW risk
        self.registry.register_tool(FileReadTool(policy))    # SAFE risk
        self.evaluator = PlanQualityEvaluator(self.registry)

    def test_manual_autonomy_rejects_autonomous_write_actions(self):
        write_step = TaskStep(
            sequence=1,
            description="Create file",
            tool_name="file.create",
            arguments={"path": "test.txt", "content": "hello"},
            risk_level=ToolRiskLevel.LOW,
            expected_result="File exists",
            verification_policy="empirical",
        )
        task = Task(user_goal="Write file", steps=[write_step])

        is_valid, issues = self.evaluator.evaluate_plan_quality(
            task=task,
            autonomy_level=AutonomyLevel.MANUAL,
        )
        self.assertFalse(is_valid)
        self.assertTrue(any("Manual autonomy does not permit" in issue for issue in issues))

    def test_supervised_autonomy_allows_low_risk_with_verification(self):
        write_step = TaskStep(
            sequence=1,
            description="Create file",
            tool_name="file.create",
            arguments={"path": "test.txt", "content": "hello"},
            risk_level=ToolRiskLevel.LOW,
            expected_result="File exists",
            verification_policy="empirical",
        )
        task = Task(user_goal="Write file", steps=[write_step])

        is_valid, issues = self.evaluator.evaluate_plan_quality(
            task=task,
            autonomy_level=AutonomyLevel.SUPERVISED,
        )
        self.assertTrue(is_valid)


if __name__ == "__main__":
    unittest.main()
