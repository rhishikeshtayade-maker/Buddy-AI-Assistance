"""BUDDY Contextual Awareness & Proactive Assistance Events.

Defines typed events emitted across the context observer lifecycle.
All events are audited and sanitized. NEVER contains raw credentials,
passwords, keystrokes, audio, or continuous screenshots.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.core.events import BaseEvent
from app.context_awareness.models import (
    ObserverStatus,
    ProactivePolicyLevel,
    SensitivityLevel,
    TriggerType,
)


@dataclass(frozen=True)
class ContextObserverEnabledEvent(BaseEvent):
    """Emitted when an observer is explicitly enabled."""

    observer_name: str = ""


@dataclass(frozen=True)
class ContextObserverDisabledEvent(BaseEvent):
    """Emitted when an observer is explicitly disabled."""

    observer_name: str = ""
    reason: str = "User/Policy disabled"


@dataclass(frozen=True)
class ContextObserverStatusChangedEvent(BaseEvent):
    """Emitted when an observer transitions operational status (e.g. HEALTHY -> DEGRADED)."""

    observer_name: str = ""
    old_status: ObserverStatus = ObserverStatus.HEALTHY
    new_status: ObserverStatus = ObserverStatus.HEALTHY
    details: str = ""


@dataclass(frozen=True)
class ContextSnapshotCreatedEvent(BaseEvent):
    """Emitted when a new privacy-filtered context snapshot is captured."""

    snapshot_id: str = ""
    activity_state: str = "unknown"
    foreground_app: Optional[str] = None
    sensitivity: SensitivityLevel = SensitivityLevel.SAFE


@dataclass(frozen=True)
class ContextTriggerDetectedEvent(BaseEvent):
    """Emitted when a contextual trigger condition fires."""

    trigger_id: str = ""
    trigger_type: str = ""
    source: str = ""
    trust: str = "untrusted"


@dataclass(frozen=True)
class ProactiveSuggestionCreatedEvent(BaseEvent):
    """Emitted when a suggestion passes relevance and interruption checks."""

    suggestion_id: str = ""
    trigger_id: str = ""
    policy_level: ProactivePolicyLevel = ProactivePolicyLevel.SUGGESTION
    relevance_score: float = 0.0
    message: str = ""


@dataclass(frozen=True)
class ProactiveSuggestionSuppressedEvent(BaseEvent):
    """Emitted when a suggestion is suppressed by quiet hours, budget, or cooldown."""

    trigger_id: str = ""
    reason: str = ""
    fingerprint: str = ""


@dataclass(frozen=True)
class ProactiveActionProposedEvent(BaseEvent):
    """Emitted when a proactive action proposal is generated."""

    proposal_id: str = ""
    tool_name: str = ""
    risk_level: int = 0
    requires_confirmation: bool = False
    requires_authentication: bool = False


@dataclass(frozen=True)
class ProactiveActionRequiresConfirmationEvent(BaseEvent):
    """Emitted when a proactive action must await explicit user confirmation."""

    proposal_id: str = ""
    tool_name: str = ""
    prompt_message: str = ""


@dataclass(frozen=True)
class ProactiveActionBlockedEvent(BaseEvent):
    """Emitted when a proactive action violates policy or attempts dangerous auto-execution."""

    proposal_id: str = ""
    tool_name: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ContextPrivacyFilterTriggeredEvent(BaseEvent):
    """Emitted when a sensitive context is detected and sanitized/suppressed."""

    app_name: str = ""
    classification: SensitivityLevel = SensitivityLevel.SENSITIVE
    action_taken: str = "redacted_and_suppressed"


@dataclass(frozen=True)
class QuietHoursSuppressionEvent(BaseEvent):
    """Emitted when proactive assistance is silenced due to active quiet hours."""

    trigger_id: str = ""
    current_time: str = ""
    quiet_window: str = ""


@dataclass(frozen=True)
class InterruptionCooldownEvent(BaseEvent):
    """Emitted when a repeated trigger is silenced due to active cooldown."""

    fingerprint: str = ""
    cooldown_seconds: float = 0.0
    elapsed_seconds: float = 0.0
