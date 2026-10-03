"""BUDDY Tool Subsystem.

Provides structured tool definitions, permission enforcement, sandboxed execution,
controlled mouse and keyboard interaction, and empirical state verification.
"""

from app.tools.base import Tool
from app.tools.builtin import register_builtin_tools
from app.tools.events import (
    InteractionConfirmationRequiredEvent,
    InteractionDeniedEvent,
    InteractionPermissionCheckedEvent,
    InteractionRequestedEvent,
    InteractionVerificationFailedEvent,
    KeyboardActionCompletedEvent,
    KeyboardActionStartedEvent,
    MouseActionCompletedEvent,
    MouseActionStartedEvent,
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
from app.tools.interaction_models import (
    InteractionAction,
    InteractionRequest,
    MouseButton,
    TextSensitivity,
    UIActionProposal,
)
from app.tools.keyboard import (
    KeyboardController,
    KeyPressTool,
    MockKeyboardController,
    TypeTextTool,
    WindowsKeyboardController,
)
from app.tools.models import (
    ToolDefinition,
    ToolExecutionStatus,
    ToolPermissionLevel,
    ToolRequest,
    ToolResult,
    ToolRiskLevel,
)
from app.tools.mouse import (
    MockMouseController,
    MouseClickTool,
    MouseController,
    MouseDoubleClickTool,
    MouseScrollTool,
    WindowsMouseController,
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
    # Core Tool Events
    "ToolRequestedEvent",
    "ToolPermissionCheckedEvent",
    "ToolConfirmationRequiredEvent",
    "ToolExecutionStartedEvent",
    "ToolExecutionCompletedEvent",
    "ToolExecutionFailedEvent",
    "ToolVerificationFailedEvent",
    "ToolDeniedEvent",
    # Interaction Models
    "MouseButton",
    "InteractionAction",
    "TextSensitivity",
    "InteractionRequest",
    "UIActionProposal",
    # Mouse & Keyboard Tools
    "MouseClickTool",
    "MouseDoubleClickTool",
    "MouseScrollTool",
    "KeyPressTool",
    "TypeTextTool",
    "MouseController",
    "WindowsMouseController",
    "MockMouseController",
    "KeyboardController",
    "WindowsKeyboardController",
    "MockKeyboardController",
    # Interaction Events
    "InteractionRequestedEvent",
    "InteractionPermissionCheckedEvent",
    "InteractionConfirmationRequiredEvent",
    "MouseActionStartedEvent",
    "MouseActionCompletedEvent",
    "KeyboardActionStartedEvent",
    "KeyboardActionCompletedEvent",
    "InteractionVerificationFailedEvent",
    "InteractionDeniedEvent",
]
