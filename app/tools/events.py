"""BUDDY Tool Execution Events.

Typed events published over the core EventBus for lifecycle tracking,
permission evaluation, execution monitoring, and auditing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.core.events import BaseEvent
from app.tools.models import ToolExecutionStatus, ToolRiskLevel


@dataclass(frozen=True)
class ToolRequestedEvent(BaseEvent):
    """Emitted when a tool invocation request is submitted."""

    request_id: str = ""
    tool_name: str = ""
    arguments: Dict[str, Any] = field(default_factory=dict)
    conversation_id: Optional[str] = None
    requested_by: str = "ai"


@dataclass(frozen=True)
class ToolPermissionCheckedEvent(BaseEvent):
    """Emitted when permission engine completes policy evaluation for a tool request."""

    request_id: str = ""
    tool_name: str = ""
    risk_level: ToolRiskLevel = ToolRiskLevel.SAFE
    allowed: bool = False
    requires_confirmation: bool = False
    requires_authentication: bool = False
    reason: str = ""


@dataclass(frozen=True)
class ToolConfirmationRequiredEvent(BaseEvent):
    """Emitted when a tool request requires explicit user confirmation before proceeding."""

    request_id: str = ""
    tool_name: str = ""
    token: str = ""
    expires_at: float = 0.0
    arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolExecutionStartedEvent(BaseEvent):
    """Emitted immediately before invoking the tool's execute method."""

    request_id: str = ""
    tool_name: str = ""


@dataclass(frozen=True)
class ToolExecutionCompletedEvent(BaseEvent):
    """Emitted when tool execution and verification successfully finish."""

    request_id: str = ""
    tool_name: str = ""
    status: ToolExecutionStatus = ToolExecutionStatus.SUCCEEDED
    execution_latency: float = 0.0


@dataclass(frozen=True)
class ToolExecutionFailedEvent(BaseEvent):
    """Emitted when tool execution encounters an error or timeout."""

    request_id: str = ""
    tool_name: str = ""
    status: ToolExecutionStatus = ToolExecutionStatus.FAILED
    error: str = ""


@dataclass(frozen=True)
class ToolVerificationFailedEvent(BaseEvent):
    """Emitted when tool execution finished without exception but verification failed."""

    request_id: str = ""
    tool_name: str = ""
    error: str = "Verification failed: system state did not match expected outcome"


@dataclass(frozen=True)
class ToolDeniedEvent(BaseEvent):
    """Emitted when a tool execution request is rejected by policy, auth, or confirmation."""

    request_id: str = ""
    tool_name: str = ""
    reason: str = "Execution denied by security policy"
