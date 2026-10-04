"""Integration tests for Reasoning layer with ToolExecutor security chain (Loop 12)."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from app.agent.models import Task, TaskStep
from app.agent.reasoning.orchestrator import LongHorizonOrchestrator
from app.core.events import EventBus
from app.security.path_policy import PathPolicy
from app.tools.builtin import FileCreateTool, FileReadTool
from app.tools.executor import ToolExecutor
from app.tools.models import ToolPermissionLevel, ToolRiskLevel
from app.tools.registry import ToolRegistry


class TestReasoningToolExecutorIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="buddy_r_tool_")
        self.workspace = Path(self.temp_dir)
        self.policy = PathPolicy(allowed_roots=[self.workspace])

        self.registry = ToolRegistry()
        self.registry.register_tool(FileCreateTool(self.policy))
        self.registry.register_tool(FileReadTool(self.policy))

        self.event_bus = EventBus()
        self.tool_executor = ToolExecutor(registry=self.registry, event_bus=self.event_bus)
        self.orchestrator = LongHorizonOrchestrator(
            registry=self.registry,
            tool_executor=self.tool_executor,
            event_bus=self.event_bus,
        )

    async def test_tool_executor_enforces_execution_and_verification(self):
        target = self.workspace / "verified.txt"
        goal = await self.orchestrator.submit_goal(f"Create file {target.name} with content 'Verified content'")
        goal.task_plan.steps[0].arguments["path"] = str(target)

        executed = await self.orchestrator.execute_goal(goal.goal_id)
        step = executed.task_plan.steps[0]

        self.assertIsNotNone(step.result)
        self.assertTrue(step.result.success)
        self.assertTrue(step.result.verified)


if __name__ == "__main__":
    unittest.main()
