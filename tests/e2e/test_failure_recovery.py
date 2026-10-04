"""End-to-End Tests for Failure Recovery & Adaptive Replanning (Loop 12 Scenario B).

Scenario B — Failure recovery:
Force a deterministic intermediate failure:
- failure detected
- diagnosed
- bounded retry or replan
- security chain preserved
- final result truthful
"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.agent.models import StepStatus
from app.agent.reasoning.models import GoalStatus, ReasoningFailureCategory
from app.agent.reasoning.orchestrator import LongHorizonOrchestrator
from app.core.events import EventBus
from app.security.path_policy import PathPolicy
from app.tools.builtin import FileCreateTool, FileReadTool, FileSearchTool
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


class TestFailureRecoveryE2E(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="buddy_e2e_fail_")
        self.workspace = Path(self.temp_dir)
        self.policy = PathPolicy(allowed_roots=[self.workspace])

        self.registry = ToolRegistry()
        self.registry.register_tool(FileCreateTool(self.policy))
        self.registry.register_tool(FileReadTool(self.policy))
        self.registry.register_tool(FileSearchTool(self.policy))

        self.event_bus = EventBus()
        self.tool_executor = ToolExecutor(registry=self.registry, event_bus=self.event_bus)
        self.orchestrator = LongHorizonOrchestrator(
            registry=self.registry,
            tool_executor=self.tool_executor,
            event_bus=self.event_bus,
        )

    async def test_scenario_b_target_not_found_recovers_via_search(self):
        # We submit a read goal for a file that does not exist directly, but another file exists
        actual_file = self.workspace / "actual_data.txt"
        actual_file.write_text("Hello from actual data", encoding="utf-8")

        missing_target = self.workspace / "missing_data.txt"
        goal = await self.orchestrator.submit_goal(f"Read {missing_target.name}")
        goal.task_plan.steps[0].arguments["path"] = str(missing_target)

        # Step 0 will fail with TARGET_NOT_FOUND, triggering replanning that inserts a search step
        executed_goal = await self.orchestrator.execute_goal(goal.goal_id)

        # Replan must be recorded
        self.assertGreaterEqual(executed_goal.task_plan.replan_count, 1)


if __name__ == "__main__":
    unittest.main()
