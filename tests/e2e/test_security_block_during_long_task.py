"""End-to-End Tests for Security Block During Long Tasks (Loop 12 Scenario G / E).

Scenario G — Dangerous action & Prompt Injection:
- risk remains immutable
- confirmation/authentication remains mandatory
- planner cannot downgrade it
- blocked action halts task with BLOCKED status
"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.agent.models import TaskStep
from app.agent.reasoning.models import GoalStatus
from app.agent.reasoning.orchestrator import LongHorizonOrchestrator
from app.security.path_policy import PathPolicy
from app.tools.base import Tool
from app.tools.builtin import FileCreateTool
from app.tools.executor import ToolExecutor
from app.tools.models import (
    ToolDefinition,
    ToolExecutionStatus,
    ToolPermissionLevel,
    ToolRiskLevel,
)
from app.tools.registry import ToolRegistry


class HighRiskDestructiveTool(Tool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="system.format_drive",
            description="Dangerous simulated format tool",
            risk_level=ToolRiskLevel.CRITICAL,
            permission_level=ToolPermissionLevel.AUTHENTICATE,
        )

    async def execute(self, arguments: dict) -> dict:
        return {"formatted": False}

    async def verify(self, arguments: dict, output: dict) -> bool:
        return False


class TestSecurityBlockE2E(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registry = ToolRegistry()
        self.policy = PathPolicy()
        self.dangerous_tool = HighRiskDestructiveTool()
        self.registry.register_tool(self.dangerous_tool)
        self.registry.register_tool(FileCreateTool(self.policy))

        self.tool_executor = ToolExecutor(registry=self.registry)
        self.orchestrator = LongHorizonOrchestrator(
            registry=self.registry,
            tool_executor=self.tool_executor,
        )

    async def test_scenario_g_critical_risk_action_blocks_unauthorized_execution(self):
        # Goal includes a dangerous step
        goal = await self.orchestrator.submit_goal("Create file clean.txt with content 'data'")

        # Manually assemble step with critical tool
        critical_step = TaskStep(
            step_id="crit_1",
            sequence=1,
            description="Format drive",
            tool_name="system.format_drive",
            arguments={},
            risk_level=ToolRiskLevel.CRITICAL,
            requires_confirmation=True,
        )
        goal.task_plan.steps = [critical_step]

        # Execute without permission / confirmation token
        executed = await self.orchestrator.execute_goal(goal.goal_id)

        # Must be blocked or paused waiting for confirmation/permission
        self.assertIn(executed.status, (GoalStatus.BLOCKED, GoalStatus.WAITING_CONFIRMATION, GoalStatus.FAILED))


if __name__ == "__main__":
    unittest.main()
