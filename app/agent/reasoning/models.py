"""BUDDY Long-Horizon Agent Reasoning Models and Data Structures (Loop 12).

Defines strongly typed, bounded, and auditable models for goals, subgoals, milestones,
checkpoints, budgets, ambiguity clarifications, and failure diagnostics.
A goal is DATA, not executable authority.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from app.agent.models import Task, TaskStep
from app.tools.models import ToolRiskLevel


class GoalStatus(str, Enum):
    """Lifecycle statuses for high-level goals and subgoals."""

    PENDING = "PENDING"
    PLANNING = "PLANNING"
    READY = "READY"
    EXECUTING = "EXECUTING"
    WAITING_CLARIFICATION = "WAITING_CLARIFICATION"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    WAITING_AUTHENTICATION = "WAITING_AUTHENTICATION"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"


class GoalPriority(str, Enum):
    """Priority classifications for goals and subgoals."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AutonomyLevel(str, Enum):
    """Governing autonomy limits for reasoning and plan execution."""

    MANUAL = "MANUAL"
    ASSISTED = "ASSISTED"
    SUPERVISED = "SUPERVISED"
    LIMITED_AUTONOMOUS = "LIMITED_AUTONOMOUS"


class ConfidenceLevel(str, Enum):
    """Explainable, bounded confidence categories."""

    VERY_LOW = "VERY_LOW"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    VERY_HIGH = "VERY_HIGH"


class StepEvaluationCategory(str, Enum):
    """Classification of step verification outcomes."""

    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    RECOVERABLE_FAILURE = "RECOVERABLE_FAILURE"
    NON_RECOVERABLE_FAILURE = "NON_RECOVERABLE_FAILURE"
    AMBIGUOUS_RESULT = "AMBIGUOUS_RESULT"
    SECURITY_BLOCK = "SECURITY_BLOCK"
    USER_REQUIRED = "USER_REQUIRED"


class ReasoningFailureCategory(str, Enum):
    """Fine-grained diagnostics categories for step and plan failures."""

    TOOL_FAILURE = "TOOL_FAILURE"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    STALE_STATE = "STALE_STATE"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    TIMEOUT = "TIMEOUT"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    EXTERNAL_CONTENT_CHANGED = "EXTERNAL_CONTENT_CHANGED"
    RESOURCE_UNAVAILABLE = "RESOURCE_UNAVAILABLE"
    AMBIGUOUS_STATE = "AMBIGUOUS_STATE"
    SECURITY_BLOCK = "SECURITY_BLOCK"
    USER_CANCELLED = "USER_CANCELLED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    UNKNOWN = "UNKNOWN"


class GoalConstraint(BaseModel):
    """Structured constraint placed on goal execution."""

    constraint_type: str = Field(..., max_length=100)
    description: str = Field(..., max_length=500)
    strict: bool = Field(default=True)

    model_config = {"extra": "forbid"}


class GoalRequirement(BaseModel):
    """Specific functional requirement derived from user objective."""

    requirement_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:6]}")
    description: str = Field(..., max_length=500)
    required_capability: str = Field(default="general", max_length=100)
    is_satisfied: bool = Field(default=False)
    verification_criteria: Optional[str] = Field(default=None, max_length=500)

    model_config = {"extra": "forbid"}


class GoalAssumption(BaseModel):
    """Explicit assumption made during reasoning that requires validation."""

    assumption_id: str = Field(default_factory=lambda: f"asm_{uuid.uuid4().hex[:6]}")
    description: str = Field(..., max_length=500)
    confidence: ConfidenceLevel = Field(default=ConfidenceLevel.MEDIUM)
    validated: bool = Field(default=False)

    model_config = {"extra": "forbid"}


class ClarificationRequest(BaseModel):
    """Structured question returned when intent or targets are ambiguous."""

    request_id: str = Field(default_factory=lambda: f"clar_{uuid.uuid4().hex[:6]}")
    question: str = Field(..., max_length=500)
    affected_requirement: str = Field(..., max_length=200)
    possible_interpretations: List[str] = Field(default_factory=list)
    risk_level: str = Field(default="MEDIUM", max_length=50)
    is_blocking: bool = Field(default=True)
    answered: bool = Field(default=False)
    chosen_interpretation: Optional[str] = Field(default=None, max_length=500)

    model_config = {"extra": "forbid"}


class ConfidenceAssessment(BaseModel):
    """Explainable, bounded confidence scoring based on deterministic factors."""

    score: float = Field(..., ge=0.0, le=1.0)
    level: ConfidenceLevel
    reason_codes: List[str] = Field(default_factory=list)
    decision_category: str = Field(default="planning", max_length=100)
    verification_result: Optional[bool] = None

    model_config = {"extra": "forbid"}

    @classmethod
    def from_score(
        cls,
        score: float,
        reason_codes: Optional[List[str]] = None,
        decision_category: str = "planning",
        verification_result: Optional[bool] = None,
    ) -> ConfidenceAssessment:
        clamped = max(0.0, min(1.0, score))
        if clamped >= 0.85:
            lvl = ConfidenceLevel.VERY_HIGH
        elif clamped >= 0.70:
            lvl = ConfidenceLevel.HIGH
        elif clamped >= 0.45:
            lvl = ConfidenceLevel.MEDIUM
        elif clamped >= 0.20:
            lvl = ConfidenceLevel.LOW
        else:
            lvl = ConfidenceLevel.VERY_LOW
        return cls(
            score=clamped,
            level=lvl,
            reason_codes=reason_codes or [],
            decision_category=decision_category,
            verification_result=verification_result,
        )


class SubGoal(BaseModel):
    """Structured subgoal partition within a long-horizon goal DAG."""

    subgoal_id: str = Field(default_factory=lambda: f"sub_{uuid.uuid4().hex[:6]}")
    goal_id: str
    description: str = Field(..., max_length=500)
    status: GoalStatus = Field(default=GoalStatus.PENDING)
    dependencies: List[str] = Field(default_factory=list, description="IDs of prerequisite subgoals")
    step_ids: List[str] = Field(default_factory=list, description="IDs of planned TaskSteps")
    success_criteria: List[str] = Field(default_factory=list)
    result_summary: Optional[str] = Field(default=None, max_length=1000)

    model_config = {"extra": "forbid"}


class Milestone(BaseModel):
    """Checkpoint marker representing major phase completion."""

    milestone_id: str = Field(default_factory=lambda: f"ms_{uuid.uuid4().hex[:6]}")
    title: str = Field(..., max_length=200)
    required_steps: List[str] = Field(default_factory=list)
    success_criteria: List[str] = Field(default_factory=list)
    status: GoalStatus = Field(default=GoalStatus.PENDING)
    verification_result: Optional[bool] = None
    completed_at: Optional[float] = None

    model_config = {"extra": "forbid"}


class Checkpoint(BaseModel):
    """Safe state snapshot allowing recovery without storing raw sensitive artifacts."""

    checkpoint_id: str = Field(default_factory=lambda: f"chk_{uuid.uuid4().hex[:6]}")
    milestone_id: Optional[str] = None
    timestamp: float = Field(default_factory=time.time)
    completed_step_ids: List[str] = Field(default_factory=list)
    state_snapshot: Dict[str, Any] = Field(
        default_factory=dict,
        description="Safe metadata only. Strictly no credentials, audio blobs, or screenshots.",
    )

    model_config = {"extra": "forbid"}

    @field_validator("state_snapshot")
    @classmethod
    def validate_safe_snapshot(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        forbidden_keys = {"password", "secret", "token", "api_key", "screenshot", "audio", "cookie"}
        for k in v.keys():
            if any(forbidden in k.lower() for forbidden in forbidden_keys):
                raise ValueError(f"Checkpoint snapshot contains forbidden key: '{k}'")
        return v


class TaskBudget(BaseModel):
    """Hard boundaries preventing infinite loops, runaway recursion, or resource leaks."""

    max_total_steps: int = Field(default=25, ge=1, le=50)
    max_replans: int = Field(default=3, ge=0, le=5)
    max_retries_per_step: int = Field(default=2, ge=0, le=5)
    max_execution_time_seconds: float = Field(default=180.0, ge=0.01, le=600.0)
    max_concurrent_operations: int = Field(default=3, ge=1, le=10)
    max_reasoning_depth: int = Field(default=5, ge=1, le=10)

    current_steps: int = Field(default=0, ge=0)
    current_replans: int = Field(default=0, ge=0)
    current_retries: Dict[str, int] = Field(default_factory=dict)
    start_time: Optional[float] = None

    model_config = {"extra": "forbid"}

    def start(self) -> None:
        if self.start_time is None:
            self.start_time = time.time()

    @property
    def elapsed_time(self) -> float:
        if self.start_time is None:
            return 0.0
        return max(0.0, time.time() - self.start_time)

    def is_exhausted(self) -> tuple[bool, Optional[str]]:
        if self.current_steps >= self.max_total_steps:
            return True, f"Max total steps ({self.max_total_steps}) reached."
        if self.current_replans >= self.max_replans:
            return True, f"Max replans ({self.max_replans}) reached."
        if self.elapsed_time >= self.max_execution_time_seconds:
            return True, f"Max execution time ({self.max_execution_time_seconds}s) reached."
        return False, None

    def record_step(self) -> None:
        self.current_steps += 1

    def record_replan(self) -> None:
        self.current_replans += 1

    def record_retry(self, step_id: str) -> bool:
        """Increment retry count for step. Returns True if within budget, False if exhausted."""
        count = self.current_retries.get(step_id, 0) + 1
        self.current_retries[step_id] = count
        return count <= self.max_retries_per_step


class FailureDiagnosis(BaseModel):
    """Diagnostic categorization of a step failure to guide replanning/retry."""

    category: ReasoningFailureCategory
    message: str = Field(..., max_length=1000)
    retryable: bool = False
    replannable: bool = False
    requires_user: bool = False
    max_retries: int = Field(default=0, ge=0, le=5)
    suggested_fix: Optional[str] = Field(default=None, max_length=500)

    model_config = {"extra": "forbid"}


class StepEvaluationResult(BaseModel):
    """Structured evaluation of a step's actual outcome against expected verification."""

    category: StepEvaluationCategory
    expected_result: Optional[str] = None
    actual_result: Optional[str] = None
    is_verified: bool = False
    diagnostic: Optional[FailureDiagnosis] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class Goal(BaseModel):
    """Strongly typed, long-horizon goal representation (data only, not authority)."""

    goal_id: str = Field(default_factory=lambda: f"goal_{uuid.uuid4().hex[:8]}")
    conversation_id: Optional[str] = None
    objective: str = Field(..., min_length=1, max_length=2000, description="User's high-level intent")
    status: GoalStatus = Field(default=GoalStatus.PENDING)
    priority: GoalPriority = Field(default=GoalPriority.MEDIUM)
    autonomy_level: AutonomyLevel = Field(default=AutonomyLevel.SUPERVISED)

    requirements: List[GoalRequirement] = Field(default_factory=list)
    constraints: List[GoalConstraint] = Field(default_factory=list)
    assumptions: List[GoalAssumption] = Field(default_factory=list)
    prohibited_actions: List[str] = Field(default_factory=list)

    subgoals: List[SubGoal] = Field(default_factory=list)
    milestones: List[Milestone] = Field(default_factory=list)
    checkpoints: List[Checkpoint] = Field(default_factory=list)

    task_plan: Optional[Task] = None
    budget: TaskBudget = Field(default_factory=TaskBudget)
    confidence: ConfidenceAssessment = Field(
        default_factory=lambda: ConfidenceAssessment.from_score(1.0, ["initial_unverified_goal"])
    )
    pending_clarification: Optional[ClarificationRequest] = None

    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}

    def get_subgoal(self, subgoal_id: str) -> Optional[SubGoal]:
        for sg in self.subgoals:
            if sg.subgoal_id == subgoal_id:
                return sg
        return None

    def get_milestone(self, milestone_id: str) -> Optional[Milestone]:
        for ms in self.milestones:
            if ms.milestone_id == milestone_id:
                return ms
        return None
