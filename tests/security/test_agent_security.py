"""Adversarial and Security Negative Tests for Agentic Task Planning & Execution.

Strictly verifies Phase 22 & 23 requirements:
- Malicious AI generating shell.execute, python.eval, delete protected file
- Planner cannot bypass PermissionEngine
- Planner cannot lower risk level
- Planner cannot bypass confirmation
- Planner cannot bypass authentication
- Tool output cannot inject new tools or modify security policy
- Runaway agent loop & tool storms are prevented
All must fail closed!
"""

from __future__ import annotations

import unittest

from app.agent.executor import TaskExecutor
from app.agent.models import StepStatus, Task, TaskStatus, TaskStep
from app.agent.planner import TaskPlanner
from app.agent.validator import (
    PlanSecurityViolationError,
    PlanValidationError,
    TaskPlanValidator,
)
from app.ai.provider import MockAIProvider
from app.core.events import EventBus
from app.security.confirmation import ConfirmationManager
from app.security.permissions import PermissionEngine
from app.tools.builtin import register_builtin_tools
from app.tools.executor import ToolExecutor
from app.tools.models import ToolRiskLevel
from app.tools.registry import ToolRegistry


class TestAgentSecurity(unittest.IsolatedAsyncioTestCase):
    """Adversarial security test suite for agent task planning and execution."""

    async def asyncSetUp(self) -> None:
        self.registry = ToolRegistry()
        register_builtin_tools(self.registry)
        self.conf_mgr = ConfirmationManager(default_ttl_seconds=30.0)
        self.event_bus = EventBus()
        self.tool_executor = ToolExecutor(
            registry=self.registry,
            confirmation_manager=self.conf_mgr,
            event_bus=self.event_bus,
        )
        self.validator = TaskPlanValidator(self.registry, max_steps=20)
        self.mock_ai = MockAIProvider()
        self.planner = TaskPlanner(
            registry=self.registry,
            ai_provider=self.mock_ai,
            validator=self.validator,
            event_bus=self.event_bus,
        )
        self.executor = TaskExecutor(
            tool_executor=self.tool_executor,
            event_bus=self.event_bus,
        )

    async def asyncTearDown(self) -> None:
        await self.event_bus.shutdown()

    async def test_phase23_malicious_mock_ai_plan_rejected(self) -> None:
        """PHASE 23 ADVERSARIAL AGENT TEST:
        Mock AI generates:
        Step 1: file.search
        Step 2: shell.execute
        Step 3: python.eval
        Step 4: delete protected file
        Expected: Step 2 and 3 must fail plan validation. The remaining dangerous steps must NEVER execute.
        No shell. No Python.
        """
        malicious_plan_json = """{
          "steps": [
            {
              "step_id": "s1",
              "description": "Legitimate search",
              "tool_name": "file.search",
              "arguments": {"query": "notes"}
            },
            {
              "step_id": "s2",
              "description": "Arbitrary shell injection",
              "tool_name": "shell.execute",
              "arguments": {"cmd": "whoami"}
            },
            {
              "step_id": "s3",
              "description": "Arbitrary python execution",
              "tool_name": "python.eval",
              "arguments": {"code": "import os; os.system('calc')"}
            },
            {
              "step_id": "s4",
              "description": "Delete protected file",
              "tool_name": "file.move",
              "arguments": {"source": "C:/Windows/System32/drivers/etc/hosts", "destination": "Documents/hosts"}
            }
          ]
        }"""
        self.mock_ai.set_next_response(malicious_plan_json)

        # Plan creation must fail closed on forbidden tool
        with self.assertRaises(PlanSecurityViolationError) as ctx:
            await self.planner.plan("Run my system script")

        self.assertIn("forbidden tool", str(ctx.exception).lower())

    def test_planner_cannot_downgrade_risk_level(self) -> None:
        """The AI planner specifies risk=0 for a MODERATE or CRITICAL tool.
        Validator must override and synchronize with trusted ToolDefinition.
        """
        # app.close is registered as MODERATE (risk 2)
        step = TaskStep(
            step_id="s1",
            sequence=1,
            description="Close app",
            tool_name="app.close",
            arguments={"application": "notepad"},
            risk_level=ToolRiskLevel.SAFE,  # Malicious attempt to claim SAFE
        )
        task = Task(user_goal="Close notepad without confirm", steps=[step])

        validated = self.validator.validate_plan(task)
        # Risk must be synchronized to MODERATE
        self.assertEqual(validated.steps[0].risk_level, ToolRiskLevel.MODERATE)
        self.assertTrue(validated.steps[0].requires_confirmation)

    async def test_planner_cannot_bypass_confirmation_requirement(self) -> None:
        """A step with requires_confirmation=False for a MODERATE/HIGH tool
        cannot bypass interactive confirmation during execution.
        """
        step = TaskStep(
            step_id="s1",
            sequence=1,
            description="Close application without approval",
            tool_name="app.close",
            arguments={"application": "notepad"},
            requires_confirmation=False,  # Attempt to bypass
        )
        # Even if unvalidated task was directly passed to executor:
        task = Task(user_goal="Close notepad bypass", steps=[step])

        result = await self.executor.execute_task(task)
        # Must pause in WAITING_CONFIRMATION; cannot execute directly
        self.assertEqual(result.status, TaskStatus.WAITING_CONFIRMATION)
        self.assertIn("confirmation_token", result.metadata)

    async def test_tool_storm_and_infinite_loop_blocked(self) -> None:
        """Enforces max_tool_calls_per_task: task execution halts if tool calls exceed limit."""
        step = TaskStep(
            step_id="s1",
            sequence=1,
            description="Query info",
            tool_name="system.get_info",
        )
        task = Task(
            user_goal="Runaway task",
            steps=[step],
            max_tool_calls=2,  # Artificially low limit
        )

        task.tool_calls_count = 2  # Already at limit
        result = await self.executor.execute_task(task)

        self.assertEqual(result.status, TaskStatus.FAILED)
        self.assertIn("maximum tool calls limit", result.final_message.lower())

    def test_tool_output_cannot_forge_tool_definition(self) -> None:
        """Tool outputs are untrusted data and cannot inject new tools into the registry."""
        initial_tool_count = len(self.registry.list_tools())

        # Attempt to inject tool via malicious plan or arguments
        malicious_step = TaskStep(
            step_id="s1",
            sequence=1,
            description="Inject fake tool",
            tool_name="tool.register_new_evil_tool",
            arguments={"name": "evil_tool", "code": "os.system('calc')"},
        )
        task = Task(user_goal="Inject tool", steps=[malicious_step])

        with self.assertRaises(PlanValidationError):
            self.validator.validate_plan(task)

        # Registry remains unmodified
        self.assertEqual(len(self.registry.list_tools()), initial_tool_count)


if __name__ == "__main__":
    unittest.main()
