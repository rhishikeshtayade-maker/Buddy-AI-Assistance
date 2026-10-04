"""BUDDY Safe Replanning Subsystem (Loop 12).

Generates adaptive replacement steps for recoverable failures while strictly preserving
security boundaries, permission tiers, and tool confirmation requirements.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from app.agent.models import StepStatus, Task, TaskStep
from app.agent.reasoning.diagnostics import FailureDiagnostician
from app.agent.reasoning.evaluator import PlanQualityEvaluator
from app.agent.reasoning.models import (
    FailureDiagnosis,
    Goal,
    ReasoningFailureCategory,
)
from app.core.exceptions import SecurityError
from app.tools.registry import ToolRegistry

logger = logging.getLogger("buddy.agent.reasoning.replanner")


class SafeReplanner:
    """Performs safe, bounded plan modification upon recoverable failures."""

    def __init__(
        self,
        registry: ToolRegistry,
        evaluator: Optional[PlanQualityEvaluator] = None,
        diagnostician: Optional[FailureDiagnostician] = None,
    ) -> None:
        self._registry = registry
        self._evaluator = evaluator or PlanQualityEvaluator(registry)
        self._diagnostician = diagnostician or FailureDiagnostician()

    def replan_failed_step(
        self,
        task: Task,
        failed_step: TaskStep,
        diagnosis: FailureDiagnosis,
        goal: Optional[Goal] = None,
    ) -> bool:
        """Attempt to safely adapt task steps to recover from failure.

        Returns:
            True if replanned successfully and validated, False otherwise.
        """
        # Hard security guard: Never replan on security blocks or permission denials without user
        if diagnosis.category in (
            ReasoningFailureCategory.SECURITY_BLOCK,
            ReasoningFailureCategory.PERMISSION_DENIED,
            ReasoningFailureCategory.AUTH_REQUIRED,
            ReasoningFailureCategory.USER_CANCELLED,
        ):
            logger.warning("Replanning rejected: category %s cannot be autonomously bypassed.", diagnosis.category)
            return False

        # Budget check
        if goal and goal.budget:
            exhausted, reason = goal.budget.is_exhausted()
            if exhausted:
                logger.warning("Replanning rejected: budget exhausted (%s)", reason)
                return False
            goal.budget.record_replan()

        task.replan_count += 1
        if task.replan_count > task.max_replans:
            logger.warning("Replanning limit exceeded (replan_count=%d)", task.replan_count)
            return False

        # 1. Target Not Found: If searching for a file failed, try broader search or alternative location
        if diagnosis.category == ReasoningFailureCategory.TARGET_NOT_FOUND:
            if failed_step.tool_name == "file.read":
                # Fallback: Insert a file search step before retrying
                search_step = TaskStep(
                    sequence=failed_step.sequence,
                    description=f"Locate candidate files for '{failed_step.arguments.get('path')}'",
                    tool_name="file.search",
                    arguments={"query": failed_step.arguments.get("path", "")},
                    expected_result="List of candidate file matches",
                )
                idx = task.current_step_index
                task.steps.insert(idx, search_step)
                # Renumber subsequent steps
                for i, s in enumerate(task.steps):
                    s.sequence = i + 1
                failed_step.status = StepStatus.PENDING

        # 2. Timeout: Adjust bounded wait or retry with verified alternative
        elif diagnosis.category == ReasoningFailureCategory.TIMEOUT:
            if "timeout" in failed_step.arguments:
                failed_step.arguments["timeout"] = min(30.0, float(failed_step.arguments.get("timeout", 5.0)) * 2)
            failed_step.status = StepStatus.PENDING
            failed_step.retries_attempted += 1

        # 3. Tool Failure: Re-initialize step as pending if retryable
        elif diagnosis.retryable:
            failed_step.status = StepStatus.PENDING
            failed_step.retries_attempted += 1

        else:
            return False

        # Validate the new plan structure through quality evaluator
        is_valid, issues = self._evaluator.evaluate_plan_quality(task, goal)
        if not is_valid:
            logger.warning("Replanned plan failed validation: %s", issues)
            return False

        logger.info("Successfully replanned task '%s' (replan #%d)", task.task_id, task.replan_count)
        return True
