"""BUDDY Browser Specialist Role (Loop 12).

Proposes web navigation, interaction, and data extraction through registered browser tools.
Cannot execute arbitrary JavaScript outside registered browser actions.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.agent.models import TaskStep
from app.agent.specialists.base import BaseSpecialist
from app.tools.models import ToolRiskLevel


class BrowserRole(BaseSpecialist):
    """Specialist dedicated to web automation and external content retrieval."""

    def __init__(self) -> None:
        super().__init__(
            role_name="browser",
            allowed_tools={
                "browser.open",
                "browser.navigate",
                "browser.extract_text",
                "browser.find",
                "browser.click",
                "browser.screenshot",
                "browser.close",
            },
        )

    def propose_steps(self, objective: str, context: Optional[Dict[str, Any]] = None) -> List[TaskStep]:
        steps: List[TaskStep] = []
        ctx = context or {}
        url = ctx.get("url", "https://duckduckgo.com")

        steps.append(
            TaskStep(
                description=f"Navigate browser to '{url}'",
                tool_name="browser.navigate",
                arguments={"url": url},
                risk_level=ToolRiskLevel.LOW,
                expected_result=f"Page '{url}' loaded successfully",
            )
        )
        steps.append(
            TaskStep(
                description="Extract page content for analysis",
                tool_name="browser.extract_text",
                arguments={"max_chars": 2000},
                risk_level=ToolRiskLevel.SAFE,
                expected_result="Text content extracted from active page",
            )
        )
        return steps
