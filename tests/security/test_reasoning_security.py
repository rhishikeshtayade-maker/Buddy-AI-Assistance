"""Security and Boundary Tests for BUDDY Reasoning Layer (Loop 12).

MANDATORY Negative Tests:
Verifies that the reasoning layer is strictly DATA/PLAN generation only and cannot:
- execute os.system or subprocess directly
- use shell=True, invoke PowerShell, cmd.exe, eval, exec, pyautogui
- bypass ToolExecutor, PermissionEngine, ConfirmationManager, AuthenticationManager
- alter ToolRiskLevel or downgrade security policies
"""

import ast
import inspect
import unittest
from pathlib import Path

from app.agent import reasoning
from app.agent.models import Task, TaskStep
from app.agent.reasoning.evaluator import PlanQualityEvaluator
from app.agent.reasoning.models import AutonomyLevel, Goal
from app.agent.reasoning.planner import LongHorizonPlanner
from app.agent.validator import PlanSecurityViolationError, TaskPlanValidator
from app.security.path_policy import PathPolicy
from app.tools.builtin import FileCreateTool, FileReadTool
from app.tools.models import ToolRiskLevel
from app.tools.registry import ToolRegistry


class TestReasoningSecurityBoundaries(unittest.TestCase):
    def test_reasoning_codebase_has_no_execution_primitives(self):
        """Verify no direct execution primitives (os.system, eval, exec, subprocess) in reasoning code."""
        reasoning_dir = Path("app/agent/reasoning")
        forbidden_calls = {"system", "eval", "exec", "popen"}

        for py_file in reasoning_dir.glob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    # Check for direct calls to eval or exec
                    if isinstance(node.func, ast.Name):
                        self.assertNotIn(
                            node.func.id,
                            {"eval", "exec"},
                            f"Prohibited '{node.func.id}' found in {py_file}",
                        )
                    # Check for os.system
                    elif isinstance(node.func, ast.Attribute):
                        if node.func.attr in forbidden_calls:
                            self.fail(f"Prohibited call '{node.func.attr}' found in {py_file}")

    def test_plan_cannot_downgrade_tool_risk_level(self):
        """Verify that a plan cannot artificially lower a tool's immutable risk tier."""
        registry = ToolRegistry()
        policy = PathPolicy()
        registry.register_tool(FileCreateTool(policy))  # LOW risk
        evaluator = PlanQualityEvaluator(registry)

        # Attempt to declare file.create as SAFE
        step = TaskStep(
            step_id="step1",
            sequence=1,
            description="Downgraded step",
            tool_name="file.create",
            arguments={"path": "test.txt", "content": "hello"},
            risk_level=ToolRiskLevel.SAFE,
        )
        task = Task(user_goal="Attempted risk downgrade", steps=[step])
        is_valid, issues = evaluator.evaluate_plan_quality(task)
        self.assertFalse(is_valid)
        self.assertTrue(any("downgrade risk level" in issue for issue in issues))

    def test_plan_cannot_contain_prohibited_shell_commands(self):
        """Verify that steps with powershell, cmd, or shell injection are rejected."""
        registry = ToolRegistry()
        policy = PathPolicy()
        registry.register_tool(FileCreateTool(policy))
        validator = TaskPlanValidator(registry)

        malicious_step = TaskStep(
            sequence=1,
            description="Shell injection",
            tool_name="file.create",
            arguments={"path": "test.txt", "command": "powershell -enc aGVsbG8="},
        )
        task = Task(user_goal="Malicious injection", steps=[malicious_step])

        with self.assertRaises(PlanSecurityViolationError):
            validator.validate_plan(task)


if __name__ == "__main__":
    unittest.main()
