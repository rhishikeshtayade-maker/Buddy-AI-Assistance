"""Unit tests for BUDDY Agent TaskPlanValidator."""

from __future__ import annotations

import unittest

from app.agent.models import Task, TaskStep
from app.agent.validator import (
    PlanSecurityViolationError,
    PlanValidationError,
    TaskPlanValidator,
)
from app.tools.builtin import register_builtin_tools
from app.tools.models import ToolRiskLevel
from app.tools.registry import ToolRegistry


class TestAgentValidator(unittest.TestCase):
    """Test plan validation against tool registry, DAG constraints, and security rules."""

    def setUp(self) -> None:
        self.registry = ToolRegistry()
        register_builtin_tools(self.registry)
        self.validator = TaskPlanValidator(self.registry, max_steps=5)

    def test_valid_plan_passes_and_synchronizes_risk(self) -> None:
        step1 = TaskStep(
            step_id="s1",
            sequence=1,
            description="Get system battery",
            tool_name="system.get_battery",
            arguments={},
            # Intentionally set wrong low risk to test sync
            risk_level=ToolRiskLevel.CRITICAL,
        )
        step2 = TaskStep(
            step_id="s2",
            sequence=2,
            description="Close application",
            tool_name="app.close",
            arguments={"application": "notepad"},
            dependencies=["s1"],
            # Intentionally set wrong low risk to test sync
            risk_level=ToolRiskLevel.SAFE,
        )

        task = Task(user_goal="Check battery and close notepad", steps=[step1, step2])
        validated = self.validator.validate_plan(task)

        # s1 is SAFE (system.get_battery is SAFE)
        self.assertEqual(validated.steps[0].risk_level, ToolRiskLevel.SAFE)
        # s2 is MODERATE (app.close is MODERATE) and requires confirmation
        self.assertEqual(validated.steps[1].risk_level, ToolRiskLevel.MODERATE)
        self.assertTrue(validated.steps[1].requires_confirmation)

    def test_plan_exceeding_max_steps_limit_rejected(self) -> None:
        # Validator has max_steps = 5
        steps = [
            TaskStep(
                step_id=f"s{i}",
                sequence=i,
                description=f"Step {i}",
                tool_name="system.get_battery",
            )
            for i in range(1, 7)
        ]
        task = Task(user_goal="Too many steps", steps=steps)

        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate_plan(task)
        self.assertIn("exceeds maximum allowed", str(ctx.exception))

    def test_unknown_tool_rejected(self) -> None:
        step = TaskStep(
            step_id="s1",
            sequence=1,
            description="Run fake tool",
            tool_name="system.hack_matrix",
            arguments={},
        )
        task = Task(user_goal="Hack matrix", steps=[step])

        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate_plan(task)
        self.assertIn("unknown tool", str(ctx.exception).lower())

    def test_forbidden_tool_rejected(self) -> None:
        forbidden_tools = [
            "shell.execute",
            "python.eval",
            "powershell",
            "cmd",
            "system.bash",
        ]
        for bad_tool in forbidden_tools:
            step = TaskStep(
                step_id="s1",
                sequence=1,
                description="Malicious tool execution",
                tool_name=bad_tool,
                arguments={},
            )
            task = Task(user_goal="Run shell", steps=[step])

            with self.assertRaises(PlanSecurityViolationError):
                self.validator.validate_plan(task)

    def test_forbidden_arguments_rejected(self) -> None:
        step = TaskStep(
            step_id="s1",
            sequence=1,
            description="Attempt injection in safe tool",
            tool_name="file.search",
            arguments={"query": "test; powershell.exe -c 'echo pwned'"},
        )
        task = Task(user_goal="Search with injection", steps=[step])

        with self.assertRaises(PlanSecurityViolationError) as ctx:
            self.validator.validate_plan(task)
        self.assertIn("prohibited command", str(ctx.exception).lower())

    def test_circular_dependency_cycle_rejected(self) -> None:
        # s1 depends on s2, s2 depends on s1
        s1 = TaskStep(step_id="s1", sequence=1, description="Step 1", tool_name="system.get_battery", dependencies=["s2"])
        s2 = TaskStep(step_id="s2", sequence=2, description="Step 2", tool_name="system.get_battery", dependencies=["s1"])
        task = Task(user_goal="Circular plan", steps=[s1, s2])

        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate_plan(task)
        self.assertIn("circular dependency cycle", str(ctx.exception).lower())

    def test_self_dependency_rejected(self) -> None:
        s1 = TaskStep(step_id="s1", sequence=1, description="Step 1", tool_name="system.get_battery", dependencies=["s1"])
        task = Task(user_goal="Self loop", steps=[s1])

        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate_plan(task)
        self.assertIn("cannot depend on itself", str(ctx.exception).lower())

    def test_unknown_dependency_id_rejected(self) -> None:
        s1 = TaskStep(step_id="s1", sequence=1, description="Step 1", tool_name="system.get_battery", dependencies=["nonexistent_step"])
        task = Task(user_goal="Dangling dep", steps=[s1])

        with self.assertRaises(PlanValidationError) as ctx:
            self.validator.validate_plan(task)
        self.assertIn("unknown dependency step", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
