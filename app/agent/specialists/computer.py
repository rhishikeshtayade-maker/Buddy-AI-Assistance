"""BUDDY Computer Specialist Role (Loop 12).

Proposes operating system, application launch, and window interaction steps.
Strictly bounded by registered system tools and UI policies.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agent.models import TaskStep
from app.agent.specialists.base import BaseSpecialist
from app.tools.models import ToolRiskLevel


class ComputerRole(BaseSpecialist):
    """Specialist dedicated to desktop system interactions."""

    def __init__(self) -> None:
        super().__init__(
            role_name="computer",
            allowed_tools={"system.info", "system.battery", "app.open", "app.list", "app.close"},
        )

    def propose_steps(self, objective: str, context: Optional[Dict[str, Any]] = None) -> List[TaskStep]:
        steps: List[TaskStep] = []
        ctx = context or {}
        app_name = ctx.get("app_name")

        if app_name:
            steps.append(
                TaskStep(
                    description=f"Launch application '{app_name}'",
                    tool_name="app.open",
                    arguments={"app_name": app_name},
                    risk_level=ToolRiskLevel.MEDIUM,
                    expected_result=f"Application '{app_name}' launched",
                )
            )
        else:
            steps.append(
                TaskStep(
                    description="Inspect active desktop system info",
                    tool_name="system.info",
                    arguments={},
                    risk_level=ToolRiskLevel.SAFE,
                    expected_result="System telemetry returned",
                )
            )
        return steps
