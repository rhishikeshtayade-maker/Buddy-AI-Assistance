"""BUDDY Tool Execution Models and Type Definitions.

Defines strongly typed models for tool metadata, risk tiers, permission categories,
tool execution requests, results, and execution lifecycle statuses.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum, IntEnum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class ToolRiskLevel(IntEnum):
    """Categorization of tool execution risk level.

    0 = SAFE: Read-only, harmless system queries (e.g., battery, CPU, OS info).
    1 = LOW: Minor non-destructive local actions (e.g., launch Notepad, create temp file).
    2 = MODERATE: Local state mutations, file movement (e.g., rename, move file).
    3 = HIGH: Destructive changes (e.g., process termination, file deletion).
    4 = CRITICAL: System-level reconfiguration, credentials, or elevated operations.
    """

    SAFE = 0
    LOW = 1
    MODERATE = 2
    HIGH = 3
    CRITICAL = 4


class ToolPermissionLevel(str, Enum):
    """Authorization requirement for tool execution."""

    NONE = "none"                   # Direct execution permitted without interactive prompt
    SESSION = "session"             # Granted once for active session
    CONFIRM = "confirm"             # Requires explicit user confirmation
    AUTHENTICATE = "authenticate"   # Requires local authentication (PIN/password)


class ToolExecutionStatus(str, Enum):
    """Lifecycle statuses during a tool execution lifecycle."""

    REQUESTED = "requested"
    AUTHORIZED = "authorized"
    CONFIRMATION_REQUIRED = "confirmation_required"
    AUTHENTICATION_REQUIRED = "authentication_required"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    TIMEOUT = "timeout"
    VERIFICATION_FAILED = "verification_failed"


class ToolDefinition(BaseModel):
    """Immutable specification and security contract for a registered tool."""

    name: str = Field(..., description="Unique tool identifier, e.g. 'system.get_info'")
    description: str = Field(..., description="Detailed description of tool capability and side effects")
    input_schema: Dict[str, Any] = Field(default_factory=dict, description="JSON schema describing expected parameters")
    output_schema: Optional[Dict[str, Any]] = Field(default=None, description="JSON schema describing output format")
    risk_level: ToolRiskLevel = Field(default=ToolRiskLevel.SAFE, description="Base risk tier of tool")
    permission_level: ToolPermissionLevel = Field(default=ToolPermissionLevel.NONE, description="Required permission tier")
    requires_confirmation: bool = Field(default=False, description="Whether explicit user confirmation is mandatory")
    requires_authentication: bool = Field(default=False, description="Whether authentication is mandatory")
    timeout_seconds: float = Field(default=10.0, ge=0.1, le=120.0, description="Maximum execution timeout in seconds")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary tool metadata")

    model_config = {
        "frozen": True,
        "extra": "forbid",
    }

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v or " " in v:
            raise ValueError(f"Invalid tool name: '{v}'. Must be non-empty and contain no spaces.")
        return v


class ToolRequest(BaseModel):
    """Structured request from AI or internal service to execute a registered tool."""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str = Field(..., description="Target registered tool identifier")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Invocation arguments")
    requested_by: str = Field(default="ai", description="Originator of request (ai, user, internal)")
    timestamp: float = Field(default_factory=time.time, description="Unix timestamp of request creation")
    conversation_id: Optional[str] = Field(default=None, description="Associated dialogue session ID")
    reason: Optional[str] = Field(default=None, description="Explanation or intent provided by AI")

    model_config = {
        "extra": "forbid",
    }


class ToolResult(BaseModel):
    """Structured result produced by tool execution and verification."""

    request_id: str = Field(..., description="ID matching the originating ToolRequest")
    tool_name: str = Field(..., description="Target tool identifier")
    success: bool = Field(default=False, description="True ONLY if both execution and verification passed")
    verified: bool = Field(default=False, description="True ONLY if post-execution verification verified system state")
    status: ToolExecutionStatus = Field(default=ToolExecutionStatus.FAILED, description="Terminal execution status")
    output: Any = Field(default=None, description="Safe result data")
    error: Optional[str] = Field(default=None, description="Error message if execution or verification failed")
    execution_latency: float = Field(default=0.0, description="Duration of execution and verification in seconds")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional result metadata")

    model_config = {
        "extra": "forbid",
    }
