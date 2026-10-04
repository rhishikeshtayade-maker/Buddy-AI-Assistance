"""BUDDY Strict Verifier Specialist Role (Loop 12).

Proposes empirical verification checks for externally observable state changes.
Ensures zero completion on unverified side-effects.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agent.models import TaskStep
from app.agent.specialists.base import BaseSpecialist
from app.tools.models import ToolRiskLevel


class VerifierRole(BaseSpecialist):
    """Specialist dedicated strictly to empirical side-effect verification."""

    def __init__(self) -> None:
        super().__init__(
            role_name="verifier",
            allowed_tools={"file.read", "file.search", "app.list", "browser.inspect"},
        )

    def propose_steps(self, objective: str, context: Optional[Dict[str, Any]] = None) -> List[TaskStep]:
        steps: List[TaskStep] = []
        ctx = context or {}

        # 1. File verification
        if "file_path" in ctx:
            steps.append(
                TaskStep(
                    description=f"Empirically verify file existence and integrity at '{ctx['file_path']}'",
                    tool_name="file.read",
                    arguments={"path": ctx["file_path"]},
                    risk_level=ToolRiskLevel.SAFE,
                    expected_result=f"File '{ctx['file_path']}' exists and is non-empty",
                    verification_policy="empirical_file_exists",
                )
            )

        # 2. Application process verification
        elif "app_name" in ctx:
            steps.append(
                TaskStep(
                    description=f"Verify application process '{ctx['app_name']}' is running",
                    tool_name="app.list",
                    arguments={},
                    risk_level=ToolRiskLevel.SAFE,
                    expected_result=f"Application '{ctx['app_name']}' present in running apps",
                )
            )

        # 3. Default state check
        else:
            steps.append(
                TaskStep(
                    description=f"Verify system state after '{objective}'",
                    tool_name="file.search",
                    arguments={"query": objective},
                    risk_level=ToolRiskLevel.SAFE,
                    expected_result="State verified",
                )
            )

        return steps
