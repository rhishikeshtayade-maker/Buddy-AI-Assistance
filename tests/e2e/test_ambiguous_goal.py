"""End-to-End Tests for Ambiguous Goal & Clarification Gating (Loop 12 Scenario C).

Scenario C — Ambiguous goal:
Provide multiple possible targets:
- ambiguity detected
- no random action
- clarification requested
- execution blocked until clarification is answered
"""

import asyncio
import unittest

from app.agent.reasoning.models import GoalStatus
from app.agent.reasoning.orchestrator import LongHorizonOrchestrator
from app.security.path_policy import PathPolicy
from app.tools.builtin import FileCreateTool, FileReadTool
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


class TestAmbiguousGoalE2E(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registry = ToolRegistry()
        policy = PathPolicy()
        self.registry.register_tool(FileCreateTool(policy))
        self.registry.register_tool(FileReadTool(policy))

        self.tool_executor = ToolExecutor(registry=self.registry)
        self.orchestrator = LongHorizonOrchestrator(
            registry=self.registry,
            tool_executor=self.tool_executor,
        )

    async def test_scenario_c_ambiguity_blocks_execution_until_resolved(self):
        # Multiple candidate targets provided for underspecified goal
        candidates = ["budget_2025.xlsx", "budget_2026.xlsx", "budget_draft.xlsx"]
        ambiguous_obj = "Open the budget spreadsheet"

        goal = await self.orchestrator.submit_goal(
            objective=ambiguous_obj,
            detected_candidates=candidates,
        )

        # 1. Must block execution
        self.assertEqual(goal.status, GoalStatus.WAITING_CLARIFICATION)
        self.assertIsNotNone(goal.pending_clarification)
        self.assertTrue(goal.pending_clarification.is_blocking)
        self.assertIn("Multiple matching targets", goal.pending_clarification.question)

        # 2. Attempting to execute unclarified goal does nothing / remains blocked
        post_exec = await self.orchestrator.execute_goal(goal.goal_id)
        self.assertEqual(post_exec.status, GoalStatus.WAITING_CLARIFICATION)

        # 3. Resolve clarification with explicit user choice
        resolved_goal = await self.orchestrator.resolve_clarification(
            goal_id=goal.goal_id,
            chosen_interpretation="budget_2026.xlsx",
        )
        self.assertEqual(resolved_goal.status, GoalStatus.READY)
        self.assertIn("budget_2026.xlsx", resolved_goal.objective)


if __name__ == "__main__":
    unittest.main()
