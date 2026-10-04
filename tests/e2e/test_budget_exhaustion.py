"""End-to-End Tests for Budget Exhaustion Gating (Loop 12 Scenario D).

Scenario D — Budget exhaustion:
Artificially constrain task budget:
- task stops
- status = budget exceeded
- no infinite loop
"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.agent.reasoning.models import GoalStatus, TaskBudget
from app.agent.reasoning.orchestrator import LongHorizonOrchestrator
from app.security.path_policy import PathPolicy
from app.tools.builtin import FileCreateTool, FileReadTool
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


class TestBudgetExhaustionE2E(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="buddy_budget_")
        self.workspace = Path(self.temp_dir)
        self.policy = PathPolicy(allowed_roots=[self.workspace])

        self.registry = ToolRegistry()
        self.registry.register_tool(FileCreateTool(self.policy))
        self.registry.register_tool(FileReadTool(self.policy))

        self.tool_executor = ToolExecutor(registry=self.registry)
        self.orchestrator = LongHorizonOrchestrator(
            registry=self.registry,
            tool_executor=self.tool_executor,
        )

    async def test_scenario_d_budget_exhaustion_halts_cleanly(self):
        target = self.workspace / "budget_test.txt"
        goal = await self.orchestrator.submit_goal(f"Create file {target.name} with content 'data'")

        # Artificially set budget max steps to 0
        goal.budget.max_total_steps = 0

        # Execute goal
        executed = await self.orchestrator.execute_goal(goal.goal_id)

        # Must halt with BUDGET_EXCEEDED
        self.assertEqual(executed.status, GoalStatus.BUDGET_EXCEEDED)


if __name__ == "__main__":
    unittest.main()
