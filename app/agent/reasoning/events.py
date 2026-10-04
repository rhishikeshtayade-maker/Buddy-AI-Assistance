"""BUDDY Long-Horizon Agent Reasoning Events (Loop 12).

Event definitions for goal lifecycle, requirement extraction, ambiguity resolution,
milestone progress, step evaluations, failure diagnostics, replanning, and budget limits.
All events contain safe metadata only; never credentials, raw screenshots, or audio.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.agent.reasoning.models import (
    ConfidenceLevel,
    GoalPriority,
    GoalStatus,
    ReasoningFailureCategory,
    StepEvaluationCategory,
)
from app.core.events import BaseEvent


@dataclass(frozen=True)
class GoalCreatedEvent(BaseEvent):
    """Emitted when a new high-level Goal is created."""

    goal_id: str = ""
    objective: str = ""
    priority: str = GoalPriority.MEDIUM.value
    conversation_id: Optional[str] = None


@dataclass(frozen=True)
class RequirementsExtractedEvent(BaseEvent):
    """Emitted when requirements, constraints, and assumptions have been parsed."""

    goal_id: str = ""
    requirement_count: int = 0
    constraint_count: int = 0
    assumption_count: int = 0
    prohibited_count: int = 0


@dataclass(frozen=True)
class ClarificationRequestedEvent(BaseEvent):
    """Emitted when goal or execution target is ambiguous and blocks execution."""

    goal_id: str = ""
    request_id: str = ""
    question: str = ""
    affected_requirement: str = ""
    is_blocking: bool = True


@dataclass(frozen=True)
class PlanCreatedEvent(BaseEvent):
    """Emitted when a long-horizon DAG plan is formulated."""

    goal_id: str = ""
    task_id: str = ""
    subgoal_count: int = 0
    step_count: int = 0
    milestone_count: int = 0


@dataclass(frozen=True)
class PlanValidatedEvent(BaseEvent):
    """Emitted when a long-horizon plan passes all quality and security evaluations."""

    goal_id: str = ""
    task_id: str = ""
    step_count: int = 0
    verification_coverage_ratio: float = 1.0


@dataclass(frozen=True)
class PlanRejectedEvent(BaseEvent):
    """Emitted when a long-horizon plan fails quality, risk, or dependency validation."""

    goal_id: str = ""
    task_id: str = ""
    reason: str = ""
    violation_category: str = "validation"


@dataclass(frozen=True)
class MilestoneStartedEvent(BaseEvent):
    """Emitted when execution begins on a milestone phase."""

    goal_id: str = ""
    milestone_id: str = ""
    title: str = ""
    step_count: int = 0


@dataclass(frozen=True)
class MilestoneCompletedEvent(BaseEvent):
    """Emitted when all steps and verification for a milestone succeed."""

    goal_id: str = ""
    milestone_id: str = ""
    title: str = ""
    verified: bool = True


@dataclass(frozen=True)
class CheckpointCreatedEvent(BaseEvent):
    """Emitted when a safe recovery state snapshot is captured."""

    goal_id: str = ""
    checkpoint_id: str = ""
    milestone_id: Optional[str] = None
    completed_steps_count: int = 0


@dataclass(frozen=True)
class StepEvaluatedEvent(BaseEvent):
    """Emitted after evaluating actual step output against expected results."""

    goal_id: str = ""
    step_id: str = ""
    category: str = StepEvaluationCategory.SUCCESS.value
    is_verified: bool = False
    details: str = ""


@dataclass(frozen=True)
class FailureDiagnosedEvent(BaseEvent):
    """Emitted when a step failure is analyzed and categorized."""

    goal_id: str = ""
    step_id: str = ""
    category: str = ReasoningFailureCategory.UNKNOWN.value
    retryable: bool = False
    replannable: bool = False
    requires_user: bool = False
    suggested_fix: Optional[str] = None


@dataclass(frozen=True)
class ReplanStartedEvent(BaseEvent):
    """Emitted when a recoverable failure triggers adaptive plan generation."""

    goal_id: str = ""
    failed_step_id: str = ""
    replan_count: int = 1
    reason: str = ""


@dataclass(frozen=True)
class ReplanCompletedEvent(BaseEvent):
    """Emitted when replanning succeeds and a new validated DAG plan is active."""

    goal_id: str = ""
    replan_count: int = 1
    new_step_count: int = 0


@dataclass(frozen=True)
class ConfidenceEvaluatedEvent(BaseEvent):
    """Emitted when confidence score and level are updated."""

    goal_id: str = ""
    score: float = 1.0
    level: str = ConfidenceLevel.HIGH.value
    decision_category: str = "planning"


@dataclass(frozen=True)
class BudgetExceededEvent(BaseEvent):
    """Emitted when execution exceeds maximum steps, replans, or time limits."""

    goal_id: str = ""
    limit_name: str = ""
    limit_value: float = 0.0
    current_value: float = 0.0


@dataclass(frozen=True)
class GoalCompletedEvent(BaseEvent):
    """Emitted when all subgoals, milestones, and final verifications succeed."""

    goal_id: str = ""
    status: str = GoalStatus.COMPLETED.value
    total_steps: int = 0
    duration_seconds: float = 0.0
    verified: bool = True


@dataclass(frozen=True)
class GoalFailedEvent(BaseEvent):
    """Emitted when goal cannot proceed and halts."""

    goal_id: str = ""
    status: str = GoalStatus.FAILED.value
    reason: str = ""
    failed_subgoal_id: Optional[str] = None


@dataclass(frozen=True)
class GoalCancelledEvent(BaseEvent):
    """Emitted when a goal is explicitly cancelled by user or safety policy."""

    goal_id: str = ""
    status: str = GoalStatus.CANCELLED.value
    reason: str = "User cancelled goal"
