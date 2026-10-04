"""End-to-End Tests for Long-Horizon Reasoning Tasks (Loop 12 Scenario A).

Scenario A — Simple long-horizon task:
Goal:
"Create a text file on Desktop called buddy_reasoning_test.txt,
write three short ideas for improving BUDDY, rename it to
buddy_reasoning_verified.txt, and verify the final file exists."
"""

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.agent.reasoning.models import GoalStatus
from app.agent.reasoning.orchestrator import LongHorizonOrchestrator
from app.core.events import EventBus
from app.security.audit import AuditLogger
from app.security.path_policy import PathPolicy
from app.tools.builtin import FileCreateTool, FileReadTool, FileRenameTool, FileSearchTool
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


class TestLongHorizonTasksE2E(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="buddy_e2e_lh_")
        self.workspace = Path(self.temp_dir)
        self.policy = PathPolicy(allowed_roots=[self.workspace])

        self.registry = ToolRegistry()
        self.registry.register_tool(FileCreateTool(self.policy))
        self.registry.register_tool(FileReadTool(self.policy))
        self.registry.register_tool(FileRenameTool(self.policy))
        self.registry.register_tool(FileSearchTool(self.policy))

        self.audit_log = self.workspace / "audit.log"
        self.audit = AuditLogger(log_path=self.audit_log)
        self.event_bus = EventBus()
        self.tool_executor = ToolExecutor(
            registry=self.registry,
            audit_logger=self.audit,
            event_bus=self.event_bus,
        )

        self.orchestrator = LongHorizonOrchestrator(
            registry=self.registry,
            tool_executor=self.tool_executor,
            event_bus=self.event_bus,
            audit_logger=self.audit,
        )

    async def test_scenario_a_file_lifecycle_and_verification(self):
        initial_file = self.workspace / "buddy_reasoning_test.txt"
        renamed_file = self.workspace / "buddy_reasoning_verified.txt"

        objective = (
            f"Create a text file on Desktop called {initial_file.name}, "
            "write three short ideas for improving BUDDY, rename it to "
            f"{renamed_file.name}, and verify the final file exists."
        )

        # 1. Submit goal and generate long-horizon plan
        goal = await self.orchestrator.submit_goal(objective)
        self.assertEqual(goal.status, GoalStatus.READY)
        self.assertGreaterEqual(len(goal.task_plan.steps), 3)

        # Map paths to actual workspace test folder
        goal.task_plan.steps[0].arguments["path"] = str(initial_file)
        goal.task_plan.steps[1].arguments["source_path"] = str(initial_file)
        goal.task_plan.steps[1].arguments["destination_path"] = str(renamed_file)
        goal.task_plan.steps[2].arguments["path"] = str(renamed_file)

        # 2. Execute plan with milestone updates & empirical verification
        executed_goal = await self.orchestrator.execute_goal(goal.goal_id)

        # Handle user confirmation if gated by security policy
        if executed_goal.status == GoalStatus.WAITING_CONFIRMATION:
            token = executed_goal.task_plan.steps[1].result.metadata.get("confirmation_token")
            executed_goal = await self.orchestrator.execute_goal(goal.goal_id, confirmation_token=token)

        # 3. Assert final status and empirical filesystem facts
        self.assertEqual(executed_goal.status, GoalStatus.COMPLETED)
        self.assertFalse(initial_file.exists(), "Old file must no longer exist after rename")
        self.assertTrue(renamed_file.exists(), "Final renamed file must exist")

        content = renamed_file.read_text(encoding="utf-8")
        self.assertIn("Idea 1", content)
        self.assertIn("Idea 2", content)
        self.assertIn("Idea 3", content)

        # 4. Verify milestones and checkpoints
        self.assertGreaterEqual(len(executed_goal.checkpoints), 1)
        self.assertTrue(all(s.result.verified for s in executed_goal.task_plan.steps))


if __name__ == "__main__":
    unittest.main()
