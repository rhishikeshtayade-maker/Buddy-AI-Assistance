"""BUDDY Tool Subsystem.

Provides structured tool definitions, permission enforcement, sandboxed execution,
and empirical state verification.
"""

from app.tools.base import Tool
from app.tools.builtin import register_builtin_tools
from app.tools.events import (
    ToolConfirmationRequiredEvent,
    ToolDeniedEvent,
    ToolExecutionCompletedEvent,
    ToolExecutionFailedEvent,
    ToolExecutionStartedEvent,
    ToolPermissionCheckedEvent,
    ToolRequestedEvent,
    ToolVerificationFailedEvent,
)
from app.tools.executor import ToolExecutor
from app.tools.models import (
    ToolDefinition,
    ToolExecutionStatus,
    ToolPermissionLevel,
    ToolRequest,
    ToolResult,
    ToolRiskLevel,
)
from app.tools.registry import ToolRegistry

__all__ = [
    "Tool",
    "ToolDefinition",
    "ToolExecutionStatus",
    "ToolPermissionLevel",
    "ToolRequest",
    "ToolResult",
    "ToolRiskLevel",
    "ToolRegistry",
    "ToolExecutor",
    "register_builtin_tools",
    "ToolRequestedEvent",
    "ToolPermissionCheckedEvent",
    "ToolConfirmationRequiredEvent",
    "ToolExecutionStartedEvent",
    "ToolExecutionCompletedEvent",
    "ToolExecutionFailedEvent",
    "ToolVerificationFailedEvent",
    "ToolDeniedEvent",
]
