"""Integration tests for Long-Horizon Agent Orchestrator (Loop 12)."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.agent.reasoning.models import AutonomyLevel, GoalStatus
from app.agent.reasoning.orchestrator import LongHorizonOrchestrator
from app.core.events import EventBus
from app.security.audit import AuditLogger
from app.security.path_policy import PathPolicy
from app.tools.builtin import FileCreateTool, FileReadTool, FileRenameTool
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


class TestLongHorizonAgentIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="buddy_lh_test_")
        self.workspace = Path(self.temp_dir)
        self.policy = PathPolicy(allowed_roots=[self.workspace])

        self.registry = ToolRegistry()
        self.registry.register_tool(FileCreateTool(self.policy))
        self.registry.register_tool(FileReadTool(self.policy))
        self.registry.register_tool(FileRenameTool(self.policy))

        self.audit_log = self.workspace / "audit.log"
        self.audit = AuditLogger(log_path=self.audit_log)
        self.event_bus = EventBus()
        self.tool_executor = ToolExecutor(registry=self.registry, audit_logger=self.audit, event_bus=self.event_bus)

        self.orchestrator = LongHorizonOrchestrator(
            registry=self.registry,
            tool_executor=self.tool_executor,
            event_bus=self.event_bus,
            audit_logger=self.audit,
            default_autonomy=AutonomyLevel.SUPERVISED,
        )

    async def test_full_goal_lifecycle_and_milestones(self):
        target_file = self.workspace / "plan.txt"
        goal_text = f"Create file {target_file.name} with content 'Project Plan'"

        goal = await self.orchestrator.submit_goal(goal_text)
        self.assertEqual(goal.status, GoalStatus.READY)
        self.assertIsNotNone(goal.task_plan)
        self.assertGreaterEqual(len(goal.milestones), 1)

        # Fix relative path to absolute workspace path for execution
        goal.task_plan.steps[0].arguments["path"] = str(target_file)

        # Execute goal
        executed_goal = await self.orchestrator.execute_goal(goal.goal_id)
        self.assertEqual(executed_goal.status, GoalStatus.COMPLETED)
        self.assertTrue(target_file.exists())
        self.assertIn("Project Plan", target_file.read_text(encoding="utf-8"))

        # Verify audit record exists
        log_text = self.audit_log.read_text(encoding="utf-8")
        self.assertIn("file.create", log_text)
        self.assertIn("SUCCEEDED", log_text)


if __name__ == "__main__":
    unittest.main()
