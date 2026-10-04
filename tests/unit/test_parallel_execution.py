"""Unit tests for Safe Parallel Coordinator (Loop 12)."""

import asyncio
import unittest
from app.agent.models import TaskStep
from app.agent.reasoning.parallel import SafeParallelCoordinator
from app.tools.executor import ToolExecutor
from app.tools.models import ToolRiskLevel
from app.tools.registry import ToolRegistry


class TestParallelExecution(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.tool_executor = ToolExecutor(registry=self.registry)
        self.coordinator = SafeParallelCoordinator(self.tool_executor)

    def test_can_parallelize_independent_read_steps(self):
        s1 = TaskStep(step_id="s1", sequence=1, description="Read 1", tool_name="system.info", arguments={}, risk_level=ToolRiskLevel.SAFE)
        s2 = TaskStep(step_id="s2", sequence=2, description="Read 2", tool_name="system.info", arguments={}, risk_level=ToolRiskLevel.SAFE)

        self.assertTrue(self.coordinator.can_parallelize_steps([s1, s2]))

    def test_reject_parallel_conflicting_or_sequential_tools(self):
        # File create is sequential-only
        s1 = TaskStep(step_id="s1", sequence=1, description="Write", tool_name="file.create", arguments={"path": "a.txt"})
        s2 = TaskStep(step_id="s2", sequence=2, description="Read", tool_name="system.info", arguments={})

        self.assertFalse(self.coordinator.can_parallelize_steps([s1, s2]))

        # High risk tool cannot parallelize
        s3 = TaskStep(step_id="s3", sequence=1, description="High", tool_name="system.info", risk_level=ToolRiskLevel.HIGH)
        s4 = TaskStep(step_id="s4", sequence=2, description="Low", tool_name="system.info", risk_level=ToolRiskLevel.LOW)
        self.assertFalse(self.coordinator.can_parallelize_steps([s3, s4]))


if __name__ == "__main__":
    unittest.main()
