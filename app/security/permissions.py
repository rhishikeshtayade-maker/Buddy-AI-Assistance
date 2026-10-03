"""BUDDY Permission Engine.

Evaluates tool execution requests against declared tool risk definitions,
enforcing mandatory confirmation and local authentication requirements.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from app.tools.models import (
    ToolDefinition,
    ToolPermissionLevel,
    ToolRequest,
    ToolRiskLevel,
)

logger = logging.getLogger("buddy.security.permissions")


@dataclass(frozen=True)
class PermissionDecision:
    """Auditable result of evaluating a tool request against security policies."""

    request_id: str
    tool_name: str
    allowed: bool
    risk_level: ToolRiskLevel
    requires_confirmation: bool
    requires_authentication: bool
    reason: str
    metadata: dict = field(default_factory=dict)


class PermissionEngine:
    """Evaluates whether an AI tool request is permissible and what gates must be satisfied.

    Key Security Rule:
    Risk classification is derived SOLELY from the trusted registered ToolDefinition
    and verified system policy metadata (e.g. InteractionPolicy target classification).
    The AI model's prompt, natural-language explanation, or request parameters can
    NEVER downgrade the risk tier or bypass confirmation/authentication.
    """

    def __init__(
        self,
        require_confirmation_for_risk2_and_above: bool = True,
        interaction_policy: Optional[Any] = None,
    ) -> None:
        self._require_confirmation_for_risk2 = require_confirmation_for_risk2_and_above
        self._interaction_policy = interaction_policy

    def set_interaction_policy(self, policy: Any) -> None:
        """Attach interaction policy for dynamic target risk evaluation."""
        self._interaction_policy = policy

    def evaluate(self, request: ToolRequest, definition: ToolDefinition) -> PermissionDecision:
        """Evaluate a tool invocation request against the tool definition.

        Args:
            request: The incoming request from AI or caller.
            definition: The trusted, registered ToolDefinition.

        Returns:
            PermissionDecision specifying authorization and gating requirements.
        """
        if request.tool_name != definition.name:
            return PermissionDecision(
                request_id=request.request_id,
                tool_name=request.tool_name,
                allowed=False,
                risk_level=definition.risk_level,
                requires_confirmation=False,
                requires_authentication=False,
                reason=f"Mismatched tool identifier: request '{request.tool_name}' vs definition '{definition.name}'.",
            )

        risk = definition.risk_level
        perm = definition.permission_level

        # Target risk elevation from trusted InteractionPolicy (Phases 5 & 11)
        # Risk can ONLY be elevated; it can NEVER be downgraded by request arguments.
        if self._interaction_policy and "target_id" in request.arguments:
            target_id = request.arguments.get("target_id")
            if target_id and isinstance(target_id, str):
                target = self._interaction_policy.get_verified_target(target_id)
                if target:
                    target_risk = self._interaction_policy.evaluate_target_risk(target)
                    if target_risk > risk:
                        risk = target_risk

        # Evaluate confirmation requirement
        requires_confirmation = definition.requires_confirmation
        if self._require_confirmation_for_risk2 and risk >= ToolRiskLevel.MODERATE:
            requires_confirmation = True

        # Evaluate authentication requirement (Critical or explicit requirement)
        requires_authentication = definition.requires_authentication
        if risk >= ToolRiskLevel.CRITICAL or perm == ToolPermissionLevel.AUTHENTICATE:
            requires_authentication = True
            requires_confirmation = True

        reason = f"Authorized for execution under risk tier {risk.name}."
        if requires_authentication:
            reason = f"Tool '{definition.name}' (risk {risk.name}) requires authentication and user confirmation."
        elif requires_confirmation:
            reason = f"Tool '{definition.name}' (risk {risk.name}) requires explicit user confirmation."

        decision = PermissionDecision(
            request_id=request.request_id,
            tool_name=definition.name,
            allowed=True,
            risk_level=risk,
            requires_confirmation=requires_confirmation,
            requires_authentication=requires_authentication,
            reason=reason,
        )

        logger.info(
            "Permission evaluated for tool '%s': risk=%s, allowed=%s, confirm=%s, auth=%s",
            definition.name,
            risk.name,
            decision.allowed,
            decision.requires_confirmation,
            decision.requires_authentication,
        )
        return decision
