"""BUDDY Coder Specialist Role (Loop 12).

Proposes file creation, editing, and movement within allowed workspace boundaries.
Cannot execute shell commands or arbitrary python directly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agent.models import TaskStep
from app.agent.specialists.base import BaseSpecialist
from app.tools.models import ToolRiskLevel


class CoderRole(BaseSpecialist):
    """Specialist dedicated to code generation and local file writing within policy."""

    def __init__(self) -> None:
        super().__init__(
            role_name="coder",
            allowed_tools={"file.create", "file.rename", "file.copy", "file.move"},
        )

    def propose_steps(self, objective: str, context: Optional[Dict[str, Any]] = None) -> List[TaskStep]:
        steps: List[TaskStep] = []
        ctx = context or {}
        target_path = ctx.get("path", "output.txt")
        content = ctx.get("content", f"Generated content for: {objective}")

        steps.append(
            TaskStep(
                description=f"Create file at '{target_path}' with generated content",
                tool_name="file.create",
                arguments={"path": target_path, "content": content},
                risk_level=ToolRiskLevel.LOW,
                expected_result=f"File '{target_path}' created on filesystem",
                verification_policy="empirical_file_exists",
            )
        )
        return steps
