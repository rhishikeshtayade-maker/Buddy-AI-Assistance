"""BUDDY Proactive Action Dispatcher & Execution Safeguards.

CRITICAL SECURITY PRINCIPLE:
Context is DATA. Context is NOT AUTHORITY.
ProactiveActionProposal is a PROPOSAL, never a direct execution command.
ALL actual actions MUST pass through ToolRegistry and ToolExecutor.
Dangerous actions (shell, deletion, credentials, network exfiltration) are NEVER auto-executed.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional

from app.context_awareness.exceptions import ProactivePolicyError
from app.context_awareness.models import (
    ProactiveActionProposal,
    ProactivePolicyLevel,
)
from app.core.events import EventBus
from app.core.logging import get_logger
from app.security.audit import AuditLogger
from app.tools.executor import ToolExecutor
from app.tools.models import (
    ToolExecutionStatus,
    ToolRequest,
    ToolResult,
    ToolRiskLevel,
)

logger = get_logger("context.proactive")

# Tools that are explicitly forbidden from being auto-executed without confirmation
DANGEROUS_ACTION_PATTERNS = {
    "file.delete",
    "file.create",
    "file.write",
    "system.execute",
    "shell",
    "cmd",
    "powershell",
    "python",
    "browser.click",
    "browser.type",
    "keyboard.type",
    "mouse.click",
}


class ProactiveActionDispatcher:
    """Dispatches proactive action proposals exclusively through ToolExecutor."""

    def __init__(
        self,
        tool_executor: ToolExecutor,
        audit_logger: Optional[AuditLogger] = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self.tool_executor = tool_executor
        self.audit_logger = audit_logger or AuditLogger()
        self.event_bus = event_bus

    async def execute_proposal(
        self,
        proposal: ProactiveActionProposal,
        confirmation_token: Optional[str] = None,
        auth_credential: Optional[str] = None,
    ) -> ToolResult:
        """Route a proactive proposal through ToolExecutor.

        Enforces:
        1. Proposal expiration
        2. Prohibiting auto-execution of dangerous or unconfirmed actions
        3. Strict routing via ToolExecutor
        """
        now = time.time()
        if now > proposal.expiration:
            logger.warning("Proactive proposal '%s' has expired.", proposal.proposal_id)
            return ToolResult(
                request_id=proposal.proposal_id,
                tool_name=proposal.suggested_tool,
                status=ToolExecutionStatus.DENIED,
                error="Proactive proposal has expired",
            )

        # Verify tool exists in registry
        tool_obj = self.tool_executor.registry.get_tool(proposal.suggested_tool)
        if not tool_obj:
            logger.warning("Proposed tool '%s' is not registered.", proposal.suggested_tool)
            return ToolResult(
                request_id=proposal.proposal_id,
                tool_name=proposal.suggested_tool,
                status=ToolExecutionStatus.DENIED,
                error=f"Tool '{proposal.suggested_tool}' is not registered",
            )
        tool_def = tool_obj.definition

        # Check dangerous tool prohibitions
        tool_lower = proposal.suggested_tool.lower()
        if (
            any(pat in tool_lower for pat in DANGEROUS_ACTION_PATTERNS)
            or tool_def.risk_level >= ToolRiskLevel.HIGH
            or proposal.risk_level >= ToolRiskLevel.HIGH
        ):
            if not confirmation_token and not auth_credential:
                logger.error("Proactive subsystem attempted dangerous action without confirmation: %s", proposal.suggested_tool)
                raise ProactivePolicyError(
                    f"Proactive action '{proposal.suggested_tool}' is classified as dangerous and requires explicit confirmation or authentication"
                )

        # If tool or proposal requires confirmation/auth and token not provided
        if (tool_def.requires_confirmation or proposal.requires_confirmation) and not confirmation_token:
            logger.info("Proactive action '%s' requires confirmation before execution.", proposal.suggested_tool)
            return ToolResult(
                request_id=proposal.proposal_id,
                tool_name=proposal.suggested_tool,
                status=ToolExecutionStatus.CONFIRMATION_REQUIRED,
                error="Action requires user confirmation",
            )

        if (tool_def.requires_authentication or proposal.requires_authentication) and not auth_credential:
            logger.info("Proactive action '%s' requires authentication before execution.", proposal.suggested_tool)
            return ToolResult(
                request_id=proposal.proposal_id,
                tool_name=proposal.suggested_tool,
                status=ToolExecutionStatus.AUTHENTICATION_REQUIRED,
                error="Action requires user authentication",
            )

        # Build formal ToolRequest
        request = ToolRequest(
            tool_name=proposal.suggested_tool,
            arguments=proposal.arguments,
            requested_by="context.proactive",
            reason=proposal.reason,
        )

        logger.info(
            "Dispatching proactive action proposal '%s' to ToolExecutor for tool '%s'",
            proposal.proposal_id,
            proposal.suggested_tool,
        )

        # Execute through standard ToolExecutor
        result = await self.tool_executor.execute(
            request=request,
            confirmation_token=confirmation_token,
            auth_credential=auth_credential,
        )

        self.audit_logger.log_event(
            event_type="PROACTIVE_ACTION_EXECUTED",
            user="system.proactive",
            resource=proposal.suggested_tool,
            action="execute",
            status="SUCCESS" if result.success else "FAILED",
            details={
                "proposal_id": proposal.proposal_id,
                "reason": proposal.reason,
                "risk_level": tool_def.risk_level.value,
                "execution_status": result.status.value,
            },
        )

        return result
