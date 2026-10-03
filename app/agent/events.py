"""BUDDY Agent Task Lifecycle Events.

Event definitions for task planning, validation, step execution,
confirmation gating, re-planning, and completion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.agent.models import FailureCategory, StepStatus, TaskStatus
from app.core.events import BaseEvent
from app.tools.models import ToolRiskLevel


@dataclass(frozen=True)
class TaskCreatedEvent(BaseEvent):
    """Emitted when a new user goal is submitted and Task instance is initialized."""

    task_id: str = ""
    user_goal: str = ""
    conversation_id: Optional[str] = None


@dataclass(frozen=True)
class TaskPlanningStartedEvent(BaseEvent):
    """Emitted when the TaskPlanner starts decomposing the user goal."""

    task_id: str = ""
    user_goal: str = ""


@dataclass(frozen=True)
class TaskPlanCreatedEvent(BaseEvent):
    """Emitted when a structured task plan with steps has been generated."""

    task_id: str = ""
    step_count: int = 0
    tools_planned: List[str] = None  # type: ignore


@dataclass(frozen=True)
class TaskPlanRejectedEvent(BaseEvent):
    """Emitted when a proposed plan fails validation or security policy."""

    task_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class TaskExecutionStartedEvent(BaseEvent):
    """Emitted when step execution commences."""

    task_id: str = ""
    total_steps: int = 0


@dataclass(frozen=True)
class TaskStepStartedEvent(BaseEvent):
    """Emitted immediately before executing an individual step."""

    task_id: str = ""
    step_id: str = ""
    sequence: int = 1
    tool_name: str = ""
    description: str = ""


@dataclass(frozen=True)
class TaskStepCompletedEvent(BaseEvent):
    """Emitted when a step succeeds and is empirically verified."""

    task_id: str = ""
    step_id: str = ""
    tool_name: str = ""
    verified: bool = True
    latency: float = 0.0


@dataclass(frozen=True)
class TaskStepFailedEvent(BaseEvent):
    """Emitted when a step fails, times out, or fails verification."""

    task_id: str = ""
    step_id: str = ""
    tool_name: str = ""
    category: FailureCategory = FailureCategory.UNKNOWN
    error: str = ""
    will_retry: bool = False


@dataclass(frozen=True)
class TaskConfirmationRequiredEvent(BaseEvent):
    """Emitted when an action in a task requires interactive user approval."""

    task_id: str = ""
    step_id: str = ""
    tool_name: str = ""
    risk_level: ToolRiskLevel = ToolRiskLevel.MODERATE
    confirmation_token: str = ""
    description: str = ""


@dataclass(frozen=True)
class TaskAuthenticationRequiredEvent(BaseEvent):
    """Emitted when an action in a task requires user authentication challenge."""

    task_id: str = ""
    step_id: str = ""
    tool_name: str = ""
    risk_level: ToolRiskLevel = ToolRiskLevel.CRITICAL
    challenge: str = ""


@dataclass(frozen=True)
class TaskPausedEvent(BaseEvent):
    """Emitted when task execution is paused (e.g. waiting for user approval)."""

    task_id: str = ""
    reason: str = ""
    waiting_status: TaskStatus = TaskStatus.PAUSED


@dataclass(frozen=True)
class TaskResumedEvent(BaseEvent):
    """Emitted when a paused task is resumed after user approval or clarification."""

    task_id: str = ""
    step_id: Optional[str] = None


@dataclass(frozen=True)
class TaskReplannedEvent(BaseEvent):
    """Emitted when an unexpected environment change triggers plan adaptation."""

    task_id: str = ""
    replan_count: int = 1
    reason: str = ""
    new_step_count: int = 0


@dataclass(frozen=True)
class TaskCompletedEvent(BaseEvent):
    """Emitted when all task steps have been successfully executed and verified."""

    task_id: str = ""
    completed_steps: int = 0
    total_latency: float = 0.0


@dataclass(frozen=True)
class TaskFailedEvent(BaseEvent):
    """Emitted when a task terminates unsuccessfully."""

    task_id: str = ""
    failed_step_id: Optional[str] = None
    reason: str = ""
    category: FailureCategory = FailureCategory.UNKNOWN


@dataclass(frozen=True)
class TaskCancelledEvent(BaseEvent):
    """Emitted when user cancels or aborts the task."""

    task_id: str = ""
    reason: str = "User cancelled task"
