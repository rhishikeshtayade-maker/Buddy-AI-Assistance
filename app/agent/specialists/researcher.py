"""BUDDY Researcher Specialist Role (Loop 12).

Proposes read-only information gathering and discovery steps (file search, read, inspection).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agent.models import TaskStep
from app.agent.specialists.base import BaseSpecialist
from app.tools.models import ToolRiskLevel


class ResearcherRole(BaseSpecialist):
    """Specialist dedicated to non-destructive discovery and data gathering."""

    def __init__(self) -> None:
        super().__init__(
            role_name="researcher",
            allowed_tools={"file.search", "file.read", "system.info", "browser.extract_text"},
        )

    def propose_steps(self, objective: str, context: Optional[Dict[str, Any]] = None) -> List[TaskStep]:
        steps: List[TaskStep] = []
        ctx = context or {}
        target_path = ctx.get("path") or ctx.get("filename")

        if target_path:
            steps.append(
                TaskStep(
                    description=f"Inspect and read content from '{target_path}'",
                    tool_name="file.read",
                    arguments={"path": target_path},
                    risk_level=ToolRiskLevel.SAFE,
                    expected_result="File content read successfully",
                )
            )
        else:
            steps.append(
                TaskStep(
                    description=f"Search for relevant files matching '{objective}'",
                    tool_name="file.search",
                    arguments={"query": objective},
                    risk_level=ToolRiskLevel.SAFE,
                    expected_result="List of candidate matching files",
                )
            )
        return steps
