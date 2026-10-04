"""BUDDY Specialist Role Abstractions (Loop 12).

Defines bounded specialist roles that propose structured task steps within their capability boundaries.
Specialists CANNOT bypass ToolExecutor, access secrets directly, or modify security policies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Set

from app.agent.models import TaskStep
from app.tools.models import ToolRiskLevel


class BaseSpecialist(ABC):
    """Abstract base specialist with strictly bounded allowed tools and propose-only authority."""

    def __init__(self, role_name: str, allowed_tools: Set[str]) -> None:
        self._role_name = role_name
        self._allowed_tools = allowed_tools

    @property
    def role_name(self) -> str:
        return self._role_name

    @property
    def allowed_tools(self) -> Set[str]:
        return set(self._allowed_tools)

    def is_tool_allowed(self, tool_name: str) -> bool:
        return tool_name in self._allowed_tools

    def validate_proposed_step(self, step: TaskStep) -> bool:
        """Verify that a proposed step strictly conforms to this specialist's role boundary."""
        if not self.is_tool_allowed(step.tool_name):
            return False
        return True

    @abstractmethod
    def propose_steps(self, objective: str, context: Optional[Dict[str, Any]] = None) -> List[TaskStep]:
        """Propose structured steps within capability boundary."""
        pass
