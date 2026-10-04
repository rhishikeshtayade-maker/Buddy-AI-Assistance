"""BUDDY Plan Quality Evaluator & Step Outcome Assessor (Loop 12).

Performs strict pre-execution plan validation (verification coverage, DAG cycles,
tool existence, autonomy limits) and empirical post-execution outcome classification.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from app.agent.models import Task, TaskStep
from app.agent.reasoning.diagnostics import FailureDiagnostician
from app.agent.reasoning.models import (
    AutonomyLevel,
    Goal,
    StepEvaluationCategory,
    StepEvaluationResult,
)
from app.core.exceptions import SecurityError, ValidationError
from app.tools.models import ToolResult, ToolRiskLevel
from app.tools.registry import ToolRegistry


class PlanQualityEvaluator:
    """Pre-execution validation engine ensuring plans meet safety, DAG, and verification gates."""

    def __init__(
        self,
        registry: ToolRegistry,
        diagnostician: Optional[FailureDiagnostician] = None,
    ) -> None:
        self._registry = registry
        self._diagnostician = diagnostician or FailureDiagnostician()

    def evaluate_plan_quality(
        self,
        task: Task,
        goal: Optional[Goal] = None,
        autonomy_level: AutonomyLevel = AutonomyLevel.SUPERVISED,
    ) -> Tuple[bool, List[str]]:
        """Validate plan completeness, DAG validity, autonomy compliance, and verification coverage.

        Returns:
            Tuple of (is_valid: bool, issues: List[str])
        """
        issues: List[str] = []

        if not task.steps:
            return False, ["Plan contains no steps."]

        step_map: Dict[str, TaskStep] = {s.step_id: s for s in task.steps}

        # 1. Dependency Graph (DAG) Check & Cycle Detection
        adj: Dict[str, List[str]] = {s.step_id: [] for s in task.steps}
        in_degree: Dict[str, int] = {s.step_id: 0 for s in task.steps}

        for s in task.steps:
            for dep in s.dependencies:
                if dep not in step_map:
                    issues.append(f"Step '{s.step_id}' depends on non-existent step '{dep}'.")
                else:
                    adj[dep].append(s.step_id)
                    in_degree[s.step_id] += 1

        # Kahn's algorithm for cycle detection
        queue = [sid for sid, deg in in_degree.items() if deg == 0]
        visited_count = 0
        while queue:
            curr = queue.pop(0)
            visited_count += 1
            for nxt in adj.get(curr, []):
                in_degree[nxt] -= 1
                if in_degree[nxt] == 0:
                    queue.append(nxt)

        if visited_count != len(task.steps):
            issues.append("Cyclic dependency detected in task plan DAG.")

        # 2. Tool existence and permission/risk tier alignment
        for s in task.steps:
            tool = self._registry.get_tool(s.tool_name)
            if not tool:
                issues.append(f"Step '{s.description}' references unregistered tool: '{s.tool_name}'.")
                continue

            # Ensure step risk_level cannot be downgraded below ToolDefinition
            if s.risk_level < tool.definition.risk_level:
                issues.append(
                    f"Step '{s.tool_name}' attempts to downgrade risk level from {tool.definition.risk_level.name} to {s.risk_level.name}."
                )

            # Autonomy level gating
            if autonomy_level == AutonomyLevel.MANUAL and s.risk_level > ToolRiskLevel.SAFE:
                issues.append(
                    f"Manual autonomy does not permit autonomous execution of {s.risk_level.name} tool '{s.tool_name}'."
                )

        # 3. Verification coverage for externally observable actions (file writes, renames, deletes)
        externally_observable = {"file.create", "file.rename", "file.move", "file.copy", "browser.upload"}
        for s in task.steps:
            if s.tool_name in externally_observable:
                has_verification = (
                    s.verification_policy is not None
                    or s.expected_result is not None
                    or any(step_map[succ].tool_name in {"file.read", "file.search", "browser.inspect"} for succ in adj.get(s.step_id, []))
                )
                if not has_verification:
                    issues.append(
                        f"Step '{s.tool_name}' modifies external state but lacks verification coverage."
                    )

        # 4. Budget check
        if goal and goal.budget:
            if len(task.steps) > goal.budget.max_total_steps:
                issues.append(
                    f"Plan step count ({len(task.steps)}) exceeds budget max ({goal.budget.max_total_steps})."
                )

        return len(issues) == 0, issues

    def evaluate_step_result(
        self,
        step: TaskStep,
        tool_result: ToolResult,
    ) -> StepEvaluationResult:
        """Classify step outcome against verification criteria without assuming success."""
        if not tool_result.success:
            diag = self._diagnostician.diagnose_failure(
                error_message=tool_result.error or "Unknown failure",
                tool_name=step.tool_name,
                tool_result=tool_result,
            )
            cat = (
                StepEvaluationCategory.SECURITY_BLOCK
                if diag.category.value == "SECURITY_BLOCK"
                else StepEvaluationCategory.USER_REQUIRED
                if (diag.requires_user or (tool_result and tool_result.status.value in ("CONFIRMATION_REQUIRED", "AUTHENTICATION_REQUIRED")))
                else StepEvaluationCategory.RECOVERABLE_FAILURE
                if diag.retryable or diag.replannable
                else StepEvaluationCategory.NON_RECOVERABLE_FAILURE
            )
            return StepEvaluationResult(
                category=cat,
                expected_result=step.expected_result,
                actual_result=tool_result.error,
                is_verified=False,
                diagnostic=diag,
            )

        # Tool completed execution, evaluate verification
        if not tool_result.verified:
            diag = self._diagnostician.diagnose_failure(
                error_message="Step execution completed but empirical verification failed",
                tool_name=step.tool_name,
                tool_result=tool_result,
            )
            return StepEvaluationResult(
                category=StepEvaluationCategory.RECOVERABLE_FAILURE,
                expected_result=step.expected_result,
                actual_result="Unverified outcome",
                is_verified=False,
                diagnostic=diag,
            )

        return StepEvaluationResult(
            category=StepEvaluationCategory.SUCCESS,
            expected_result=step.expected_result,
            actual_result="Verified successfully",
            is_verified=True,
            diagnostic=None,
        )
