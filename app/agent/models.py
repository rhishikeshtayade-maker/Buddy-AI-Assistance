"""BUDDY Agent Task Models and Type Definitions.

Defines strongly typed representations of tasks, steps, lifecycle statuses,
execution policies, and task outcomes.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.tools.models import ToolResult, ToolRiskLevel


class TaskStatus(str, Enum):
    """Lifecycle states of an agentic multi-step task."""

    PENDING = "PENDING"
    PLANNING = "PLANNING"
    READY = "READY"
    EXECUTING = "EXECUTING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    WAITING_AUTHENTICATION = "WAITING_AUTHENTICATION"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


class StepStatus(str, Enum):
    """Lifecycle states of an individual task step."""

    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    WAITING_PERMISSION = "WAITING_PERMISSION"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    WAITING_AUTHENTICATION = "WAITING_AUTHENTICATION"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class FailureCategory(str, Enum):
    """Classification of step or execution failures."""

    TRANSIENT = "TRANSIENT"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    SCREEN_CHANGED = "SCREEN_CHANGED"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    SECURITY_BLOCKED = "SECURITY_BLOCKED"
    DEPENDENCY_FAILED = "DEPENDENCY_FAILED"
    UNKNOWN = "UNKNOWN"


class RetryPolicy(BaseModel):
    """Configuration for bounded retries upon failure."""

    max_retries: int = Field(default=2, ge=0, le=5)
    retry_delay_seconds: float = Field(default=0.5, ge=0.0, le=10.0)
    retryable_categories: List[FailureCategory] = Field(
        default_factory=lambda: [
            FailureCategory.TRANSIENT,
            FailureCategory.SCREEN_CHANGED,
            FailureCategory.TARGET_NOT_FOUND,
            FailureCategory.TOOL_TIMEOUT,
        ]
    )

    model_config = {"frozen": True}


class TaskStep(BaseModel):
    """An individual atomic, verifiable action within a Task."""

    step_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    sequence: int = Field(default=1, ge=1)
    description: str = Field(..., description="Human-readable description of this step")
    tool_name: str = Field(..., description="Target registered tool identifier")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Invocation arguments")
    status: StepStatus = Field(default=StepStatus.PENDING)
    dependencies: List[str] = Field(default_factory=list, description="Step IDs that must succeed before this step")
    risk_level: ToolRiskLevel = Field(default=ToolRiskLevel.LOW)
    requires_confirmation: bool = Field(default=False)
    requires_authentication: bool = Field(default=False)
    expected_result: Optional[str] = None
    verification_policy: Optional[str] = None
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    retries_attempted: int = Field(default=0)
    result: Optional[ToolResult] = None
    error: Optional[str] = None
    failure_category: Optional[FailureCategory] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class Task(BaseModel):
    """A multi-step goal plan composed of ordered, verifiable steps."""

    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: Optional[str] = None
    user_goal: str = Field(..., description="The original natural language goal from user")
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    steps: List[TaskStep] = Field(default_factory=list)
    current_step_index: int = Field(default=0, ge=0)
    max_steps: int = Field(default=20, ge=1, le=50)
    max_tool_calls: int = Field(default=30, ge=1, le=100)
    tool_calls_count: int = Field(default=0, ge=0)
    replan_count: int = Field(default=0, ge=0)
    max_replans: int = Field(default=3, ge=0, le=5)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    @property
    def current_step(self) -> Optional[TaskStep]:
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    def get_step_by_id(self, step_id: str) -> Optional[TaskStep]:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None


class TaskResult(BaseModel):
    """Final auditable outcome of an executed Task."""

    task_id: str
    status: TaskStatus
    completed_steps: List[str] = Field(default_factory=list)
    failed_step: Optional[str] = None
    final_message: str
    verified: bool = False
    execution_latency: float = 0.0
    tool_calls_count: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}
