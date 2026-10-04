"""Unit tests for Long-Horizon DAG Planner (Loop 12)."""

import asyncio
import unittest
from app.agent.models import Task, TaskStep
from app.agent.reasoning.extractor import GoalRequirementExtractor
from app.agent.reasoning.models import GoalStatus
from app.agent.reasoning.planner import LongHorizonPlanner
from app.security.path_policy import PathPolicy
from app.tools.builtin import FileCreateTool, FileReadTool, FileRenameTool
from app.tools.registry import ToolRegistry


class TestReasoningPlanner(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.registry = ToolRegistry()
        policy = PathPolicy()
        self.registry.register_tool(FileCreateTool(policy))
        self.registry.register_tool(FileReadTool(policy))
        self.registry.register_tool(FileRenameTool(policy))
        self.planner = LongHorizonPlanner(registry=self.registry)
        self.extractor = GoalRequirementExtractor()

    async def test_create_dag_plan_with_milestones(self):
        goal = self.extractor.extract_goal("Create file notes.txt, rename it to notes_final.txt, and verify it")
        task = await self.planner.create_long_horizon_plan(goal)

        self.assertGreaterEqual(len(task.steps), 2)
        self.assertGreaterEqual(len(goal.subgoals), 1)
        self.assertGreaterEqual(len(goal.milestones), 1)
        self.assertEqual(goal.status, GoalStatus.READY)

        # Check dependencies in DAG
        step_ids = [s.step_id for s in task.steps]
        # Step 2 depends on step 1
        self.assertIn(step_ids[0], task.steps[1].dependencies)

    async def test_verification_policy_augmented(self):
        goal = self.extractor.extract_goal("Create file test.txt with content 'data'")
        task = await self.planner.create_long_horizon_plan(goal)

        self.assertTrue(any(s.verification_policy is not None for s in task.steps))


if __name__ == "__main__":
    unittest.main()
