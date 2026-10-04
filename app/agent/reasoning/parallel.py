"""BUDDY Safe Parallel Execution Coordinator (Loop 12).

Discovers and safely coordinates parallel execution of independent, read-only or
non-conflicting steps. Strictly preserves ToolExecutor enforcement and verification.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Set, Tuple

from app.agent.models import StepStatus, Task, TaskStep
from app.tools.executor import ToolExecutor
from app.tools.models import ToolRequest, ToolResult, ToolRiskLevel

logger = logging.getLogger("buddy.agent.reasoning.parallel")


class SafeParallelCoordinator:
    """Identifies independent, non-conflicting steps and executes them concurrently."""

    # Disallowed tools for parallel execution to prevent UI, session, or filesystem race conditions
    _SEQUENTIAL_ONLY_TOOLS = {
        "mouse.click", "mouse.double_click", "mouse.scroll",
        "keyboard.type_text", "keyboard.key_press",
        "file.create", "file.rename", "file.move", "file.copy",
        "browser.navigate", "browser.click", "browser.type", "browser.upload", "browser.download",
    }

    def __init__(self, tool_executor: ToolExecutor, max_concurrency: int = 3) -> None:
        self._tool_executor = tool_executor
        self._semaphore = asyncio.Semaphore(max_concurrency)

    def can_parallelize_steps(self, steps: List[TaskStep]) -> bool:
        """Check if a set of steps can safely run concurrently."""
        if len(steps) <= 1:
            return False

        # All steps must be read-only / low-risk
        for s in steps:
            if s.tool_name in self._SEQUENTIAL_ONLY_TOOLS:
                return False
            if s.risk_level > ToolRiskLevel.LOW:
                return False
            if s.requires_confirmation or s.requires_authentication:
                return False

        # No interdependent steps
        step_ids = {s.step_id for s in steps}
        for s in steps:
            if any(dep in step_ids for dep in s.dependencies):
                return False

        return True

    async def execute_parallel_steps(
        self,
        steps: List[TaskStep],
        task_id: str,
    ) -> List[Tuple[TaskStep, ToolResult]]:
        """Execute independent steps concurrently through ToolExecutor."""
        async def _exec_single(step: TaskStep) -> Tuple[TaskStep, ToolResult]:
            async with self._semaphore:
                step.status = StepStatus.EXECUTING
                req = ToolRequest(
                    tool_name=step.tool_name,
                    arguments=step.arguments,
                )
                res = await self._tool_executor.execute(req)
                step.result = res
                step.status = StepStatus.SUCCEEDED if res.success and res.verified else StepStatus.FAILED
                return step, res

        tasks = [_exec_single(s) for s in steps]
        return await asyncio.gather(*tasks)
