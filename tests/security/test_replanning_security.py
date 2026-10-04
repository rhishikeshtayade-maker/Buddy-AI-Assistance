"""Security tests for Safe Replanning (Loop 12).

Verifies that replanning cannot bypass security policies, escalate tool privileges,
or circumvent user confirmation requirements.
"""

import unittest
from app.agent.models import Task, TaskStep
from app.agent.reasoning.diagnostics import FailureDiagnostician
from app.agent.reasoning.evaluator import PlanQualityEvaluator
from app.agent.reasoning.models import FailureDiagnosis, ReasoningFailureCategory
from app.agent.reasoning.replanner import SafeReplanner
from app.security.path_policy import PathPolicy
from app.tools.builtin import FileCreateTool, FileReadTool
from app.tools.models import ToolRiskLevel
from app.tools.registry import ToolRegistry


class TestReplanningSecurity(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        policy = PathPolicy()
        self.registry.register_tool(FileCreateTool(policy))
        self.registry.register_tool(FileReadTool(policy))
        self.evaluator = PlanQualityEvaluator(self.registry)
        self.diagnostician = FailureDiagnostician()
        self.replanner = SafeReplanner(self.registry, self.evaluator, self.diagnostician)

    def test_replanning_blocks_security_violations(self):
        step = TaskStep(
            sequence=1,
            description="Attempted injection",
            tool_name="file.create",
            arguments={"path": "exploit.bat"},
        )
        task = Task(user_goal="Exploit", steps=[step])
        diag = FailureDiagnosis(
            category=ReasoningFailureCategory.SECURITY_BLOCK,
            message="Policy violation",
            retryable=False,
            replannable=False,
            requires_user=True,
        )

        # Replanning MUST fail closed
        result = self.replanner.replan_failed_step(task, step, diag)
        self.assertFalse(result)
        self.assertEqual(task.replan_count, 0)

    def test_replanning_respects_max_replans_limit(self):
        step = TaskStep(
            sequence=1,
            description="Read",
            tool_name="file.read",
            arguments={"path": "missing.txt"},
        )
        task = Task(user_goal="Test", steps=[step], max_replans=2, replan_count=2)
        diag = FailureDiagnosis(
            category=ReasoningFailureCategory.TARGET_NOT_FOUND,
            message="Missing",
            retryable=True,
            replannable=True,
        )

        # Already at max_replans
        result = self.replanner.replan_failed_step(task, step, diag)
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
