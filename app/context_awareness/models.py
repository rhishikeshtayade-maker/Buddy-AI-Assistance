"""BUDDY Contextual Awareness & Proactive Assistance Data Models.

Defines strongly typed Pydantic models for context snapshots, observers,
triggers, suggestions, proposals, interruption budgets, and privacy classifications.

CRITICAL SECURITY REQUIREMENT:
Context is DATA. Context is NOT AUTHORITY.
ContextSnapshot must NEVER store raw screenshots, raw audio, or keystrokes.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from app.tools.models import ToolRiskLevel


class ActivityState(str, Enum):
    """Coarse user activity state."""

    ACTIVE = "active"
    IDLE = "idle"
    AWAY = "away"
    UNKNOWN = "unknown"


class TrustClassification(str, Enum):
    """Data trust boundary level."""

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class SensitivityLevel(str, Enum):
    """Context sensitivity classification."""

    SAFE = "safe"
    SENSITIVE = "sensitive"
    HIGHLY_SENSITIVE = "highly_sensitive"
    BLOCKED = "blocked"


class ProactivePolicyLevel(str, Enum):
    """Proactive assistance policy tiers."""

    PASSIVE = "passive"                           # Informational notification only, no action
    SUGGESTION = "suggestion"                     # Asks user if assistance is desired
    CONFIRMATION_REQUIRED = "confirmation_required"  # Proposes action, requires explicit confirmation
    AUTH_REQUIRED = "auth_required"               # High-risk action requires local authentication
    BLOCKED = "blocked"                           # Prohibited by security policy


class InterruptionBudgetDecision(str, Enum):
    """Outcome of interruption budget evaluation."""

    ALLOWED = "allowed"
    COOLDOWN_SUPPRESSED = "cooldown_suppressed"
    HOURLY_LIMIT_EXCEEDED = "hourly_limit_exceeded"
    QUIET_HOURS_SUPPRESSED = "quiet_hours_suppressed"
    SENSITIVE_CONTEXT_SUPPRESSED = "sensitive_context_suppressed"


class ObserverStatus(str, Enum):
    """Operational status of a context observer."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    FAILED = "failed"


class TriggerType(str, Enum):
    """Types of contextual events and triggers."""

    AppOpened = "app.opened"
    AppFocused = "app.focused"
    AppClosed = "app.closed"
    UserBecameIdle = "user.became_idle"
    UserBecameActive = "user.became_active"
    ScheduledTimeReached = "scheduler.time_reached"
    CalendarEventApproaching = "calendar.event_approaching"
    NotificationReceived = "notification.received"
    BrowserContextChanged = "browser.context_changed"
    TaskDeadlineApproaching = "task.deadline_approaching"
    TaskCompleted = "task.completed"
    TaskFailed = "task.failed"


class ForegroundAppInfo(BaseModel):
    """Metadata regarding the currently focused foreground application."""

    process_name: str = Field(..., description="Process name, e.g. code.exe")
    app_identity: str = Field(..., description="Normalized application identifier, e.g. 'VS Code'")
    window_title: Optional[str] = Field(default=None, description="Window title if safe and permitted")
    pid: Optional[int] = Field(default=None, description="Process ID")
    is_sensitive: bool = Field(default=False, description="Whether application handles sensitive credentials")

    @field_validator("window_title")
    @classmethod
    def truncate_window_title(cls, v: Optional[str]) -> Optional[str]:
        if v and len(v) > 200:
            return v[:197] + "..."
        return v


class NotificationMetadata(BaseModel):
    """Untrusted notification event metadata."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_app: str = Field(..., description="Source application identifier")
    timestamp: float = Field(default_factory=time.time)
    title: Optional[str] = Field(default=None, description="Notification header/title")
    preview: Optional[str] = Field(default=None, description="Bounded notification summary")
    sensitivity: SensitivityLevel = Field(default=SensitivityLevel.SAFE)
    trust: TrustClassification = Field(
        default=TrustClassification.UNTRUSTED,
        description="External notifications are always untrusted data"
    )

    @field_validator("preview")
    @classmethod
    def bound_preview(cls, v: Optional[str]) -> Optional[str]:
        if v and len(v) > 120:
            return v[:117] + "..."
        return v


class CalendarEvent(BaseModel):
    """Untrusted calendar entry."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str = Field(..., description="Calendar event title")
    start_time: float = Field(..., description="Unix timestamp of event start")
    end_time: Optional[float] = Field(default=None, description="Unix timestamp of event end")
    location: Optional[str] = Field(default=None)
    description: Optional[str] = Field(default=None, description="Untrusted event notes/body")
    is_critical: bool = Field(default=False, description="User flagged as critical reminder")
    trust: TrustClassification = Field(
        default=TrustClassification.UNTRUSTED,
        description="Calendar entries are untrusted data"
    )

    @field_validator("description")
    @classmethod
    def bound_description(cls, v: Optional[str]) -> Optional[str]:
        if v and len(v) > 300:
            return v[:297] + "..."
        return v


class ScheduledItem(BaseModel):
    """Contextual scheduler item."""

    item_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str = Field(..., description="Name or label of scheduled item")
    target_time: float = Field(..., description="Scheduled unix execution timestamp")
    recurring_interval_seconds: Optional[float] = Field(default=None)
    cron_expression: Optional[str] = Field(default=None)
    payload: Dict[str, Any] = Field(default_factory=dict)
    is_critical: bool = Field(default=False)
    cancelled: bool = Field(default=False)


class BrowserContextInfo(BaseModel):
    """Permitted safe browser metadata."""

    active_domain: Optional[str] = Field(default=None)
    page_category: Optional[str] = Field(default=None)
    active_task_id: Optional[str] = Field(default=None)
    is_sensitive: bool = Field(default=False)
    trust: TrustClassification = Field(
        default=TrustClassification.UNTRUSTED,
        description="Web context is untrusted external data"
    )


class TaskStateContext(BaseModel):
    """BUDDY active task context."""

    task_id: Optional[str] = None
    task_name: Optional[str] = None
    status: Optional[str] = None
    deadline: Optional[float] = None


class ContextSnapshot(BaseModel):
    """Aggregated environmental snapshot at a point in time.

    Contains ONLY coarse, privacy-sanitized metadata.
    NEVER contains raw screen captures, raw audio recordings, or keystrokes.
    """

    snapshot_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    foreground_app: Optional[ForegroundAppInfo] = None
    window_title: Optional[str] = None
    activity_state: ActivityState = Field(default=ActivityState.UNKNOWN)
    active_buddy_task: Optional[TaskStateContext] = None
    relevant_scheduled_event: Optional[ScheduledItem] = None
    notification_metadata: Optional[NotificationMetadata] = None
    browser_context: Optional[BrowserContextInfo] = None
    user_preference_context: Dict[str, Any] = Field(default_factory=dict)
    source_metadata: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    sensitivity: SensitivityLevel = Field(default=SensitivityLevel.SAFE)


class ContextTrigger(BaseModel):
    """Normalized contextual trigger event."""

    trigger_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trigger_type: TriggerType = Field(..., description="Typed trigger category")
    timestamp: float = Field(default_factory=time.time)
    source: str = Field(..., description="Observer or source emitting trigger")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    sensitivity: SensitivityLevel = Field(default=SensitivityLevel.SAFE)
    payload: Dict[str, Any] = Field(default_factory=dict)
    trust: TrustClassification = Field(
        default=TrustClassification.UNTRUSTED,
        description="External payloads must be marked untrusted"
    )


class ProactiveActionProposal(BaseModel):
    """Formal, verifiable action proposal generated by contextual awareness.

    Does NOT execute directly. Enters ToolExecutor via standard policy.
    """

    proposal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    reason: str = Field(..., description="Human-readable justification for the proposal")
    triggering_context_id: str = Field(..., description="ID of trigger or snapshot that prompted action")
    suggested_tool: str = Field(..., description="Registered tool identifier, e.g. 'system.get_info'")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Typed tool arguments")
    risk_level: ToolRiskLevel = Field(default=ToolRiskLevel.SAFE)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    expiration: float = Field(..., description="Timestamp after which proposal expires")
    requires_confirmation: bool = Field(default=False)
    requires_authentication: bool = Field(default=False)


class ContextualSuggestion(BaseModel):
    """Proactive suggestion surfaced to user or agent."""

    suggestion_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    trigger_id: str = Field(..., description="Trigger triggering the suggestion")
    message: str = Field(..., description="User-facing recommendation or alert text")
    relevance_score: float = Field(default=0.8, ge=0.0, le=1.0)
    policy_level: ProactivePolicyLevel = Field(default=ProactivePolicyLevel.SUGGESTION)
    action_proposal: Optional[ProactiveActionProposal] = None
    created_at: float = Field(default_factory=time.time)
    expires_at: float = Field(..., description="Expiry timestamp")
    fingerprint: str = Field(..., description="Deduplication fingerprint")


class ContextAwarenessUIState(BaseModel):
    """Read-only view model for UI presentation."""

    context_awareness_enabled: bool = True
    proactive_assistance_enabled: bool = True
    foreground_app: Optional[str] = None
    activity_state: str = "unknown"
    observers: Dict[str, str] = Field(default_factory=dict)
    quiet_hours_active: bool = False
    quiet_hours_schedule: str = "22:00 -> 07:00"
    recent_suggestions: List[Dict[str, Any]] = Field(default_factory=list)
