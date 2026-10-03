"""BUDDY Task Plan Validator.

Validates that structured task plans strictly conform to registered tools,
safe input schemas, step limits, dependency graphs, and immutability of security risk tiers.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Set

from app.agent.models import Task, TaskStep
from app.agent.policies import (
    contains_forbidden_arguments,
    is_forbidden_tool,
)
from app.core.exceptions import SecurityError, ValidationError
from app.tools.models import ToolRiskLevel
from app.tools.registry import ToolRegistry

logger = logging.getLogger("buddy.agent.validator")


class PlanValidationError(ValidationError):
    """Raised when a proposed plan fails structure, limit, or dependency validation."""


class PlanSecurityViolationError(PlanValidationError, SecurityError):
    """Raised when a plan attempts forbidden tool execution, injection, or risk tampering."""


class TaskPlanValidator:
    """Validates Task plans against ToolRegistry, DAG dependency rules, and security boundaries."""

    def __init__(self, registry: ToolRegistry, max_steps: int = 20) -> None:
        self._registry = registry
        self._max_steps = max_steps

    def validate_plan(self, task: Task) -> Task:
        """Thoroughly validate a Task plan before execution.

        Checks:
        1. Non-empty plan within step limit.
        2. Forbidden tool name rejection.
        3. Forbidden argument injection detection.
        4. Tool existence in ToolRegistry.
        5. Dependency resolution & cycle detection (DAG check).
        6. Risk tier and confirmation/auth enforcement from ToolDefinition.

        Returns:
            The validated Task with security metadata synchronized from trusted ToolDefinitions.

        Raises:
            PlanValidationError: If structural or dependency constraints are violated.
            PlanSecurityViolationError: If security boundaries or forbidden commands are attempted.
        """
        steps = task.steps
        if not steps:
            raise PlanValidationError("Task plan contains no steps.")

        if len(steps) > self._max_steps:
            raise PlanValidationError(
                f"Task plan step count ({len(steps)}) exceeds maximum allowed ({self._max_steps})."
            )

        step_ids: Set[str] = {s.step_id for s in steps}
        if len(step_ids) != len(steps):
            raise PlanValidationError("Duplicate step_ids detected in plan.")

        # 1. Inspect each step against tools and security policies
        for idx, step in enumerate(steps):
            # Check forbidden tool
            if is_forbidden_tool(step.tool_name):
                raise PlanSecurityViolationError(
                    f"Step {step.sequence} attempts to invoke forbidden tool: '{step.tool_name}'."
                )

            # Check forbidden argument patterns
            if contains_forbidden_arguments(step.arguments):
                raise PlanSecurityViolationError(
                    f"Step {step.sequence} contains prohibited command/script arguments in '{step.tool_name}'."
                )

            # Check tool registration
            tool = self._registry.get_tool(step.tool_name)
            if not tool:
                raise PlanValidationError(
                    f"Step {step.sequence} specifies unknown tool: '{step.tool_name}'."
                )

            definition = tool.definition

            # CRITICAL SECURITY RULE: The planner cannot assign or downgrade risk.
            # Risk is derived SOLELY from the registered, immutable ToolDefinition.
            step.risk_level = definition.risk_level

            # Enforce confirmation requirement
            requires_confirm = definition.requires_confirmation
            if definition.risk_level >= ToolRiskLevel.MODERATE:
                requires_confirm = True
            step.requires_confirmation = requires_confirm

            # Enforce authentication requirement
            requires_auth = definition.requires_authentication
            if definition.risk_level >= ToolRiskLevel.CRITICAL:
                requires_auth = True
            step.requires_authentication = requires_auth

        # 2. Dependency Graph Validation (DAG & Cycle Detection)
        self._validate_dependencies(steps)

        logger.info(
            "Task plan for '%s' validated successfully (%d steps, max risk %s).",
            task.user_goal,
            len(steps),
            max(s.risk_level for s in steps).name if steps else "NONE",
        )
        return task

    def _validate_dependencies(self, steps: List[TaskStep]) -> None:
        """Validate step dependencies and assert the graph is an acyclic directed graph (DAG)."""
        valid_ids: Set[str] = {s.step_id for s in steps}
        graph: Dict[str, List[str]] = {}

        for step in steps:
            for dep_id in step.dependencies:
                if dep_id not in valid_ids:
                    raise PlanValidationError(
                        f"Step '{step.step_id}' references unknown dependency step '{dep_id}'."
                    )
                if dep_id == step.step_id:
                    raise PlanValidationError(
                        f"Step '{step.step_id}' cannot depend on itself (circular dependency)."
                    )
            graph[step.step_id] = list(step.dependencies)

        # Detect cycles using DFS cycle detection
        visited: Dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=visited

        def dfs(node: str) -> None:
            visited[node] = 1  # visiting
            for neighbor in graph.get(node, []):
                state = visited.get(neighbor, 0)
                if state == 1:
                    raise PlanValidationError(
                        f"Circular dependency cycle detected involving step '{neighbor}'."
                    )
                if state == 0:
                    dfs(neighbor)
            visited[node] = 2  # visited

        for step in steps:
            if visited.get(step.step_id, 0) == 0:
                dfs(step.step_id)
