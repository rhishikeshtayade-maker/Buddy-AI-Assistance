"""BUDDY Contextual Awareness & Proactive Assistance Subsystem.

Provides non-surveillance environmental context awareness and deterministic
proactive assistance strictly subordinate to security policies.

CRITICAL SECURITY PRINCIPLE:
Context is DATA. Context is NOT AUTHORITY.
All computer actions must pass through ToolRegistry and ToolExecutor.
"""

from __future__ import annotations

from app.context_awareness.activity import ActivityObserver
from app.context_awareness.calendar import (
    CalendarObserver,
    CalendarProvider,
    LocalCalendarProvider,
    MockCalendarProvider,
)
from app.context_awareness.config import ContextAwarenessConfig
from app.context_awareness.deduplication import DeduplicationManager
from app.context_awareness.events import (
    ContextObserverDisabledEvent,
    ContextObserverEnabledEvent,
    ContextObserverStatusChangedEvent,
    ContextPrivacyFilterTriggeredEvent,
    ContextSnapshotCreatedEvent,
    ContextTriggerDetectedEvent,
    InterruptionCooldownEvent,
    ProactiveActionBlockedEvent,
    ProactiveActionProposedEvent,
    ProactiveActionRequiresConfirmationEvent,
    ProactiveSuggestionCreatedEvent,
    ProactiveSuggestionSuppressedEvent,
    QuietHoursSuppressionEvent,
)
from app.context_awareness.exceptions import (
    ContextAwarenessError,
    InterruptionBlockedError,
    ObserverDegradedError,
    ObserverError,
    ObserverPermissionError,
    PrivacyViolationError,
    ProactivePolicyError,
    SchedulerError,
    SensitiveContextSuppressedError,
    TriggerError,
)
from app.context_awareness.foreground import ForegroundObserver
from app.context_awareness.interruption import InterruptionManager
from app.context_awareness.models import (
    ActivityState,
    BrowserContextInfo,
    CalendarEvent,
    ContextAwarenessUIState,
    ContextSnapshot,
    ContextTrigger,
    ContextualSuggestion,
    ForegroundAppInfo,
    InterruptionBudgetDecision,
    NotificationMetadata,
    ObserverStatus,
    ProactiveActionProposal,
    ProactivePolicyLevel,
    ScheduledItem,
    SensitivityLevel,
    TaskStateContext,
    TriggerType,
    TrustClassification,
)
from app.context_awareness.notifications import (
    LocalNotificationProvider,
    MockNotificationProvider,
    NotificationObserver,
    NotificationProvider,
)
from app.context_awareness.observers import BaseObserver
from app.context_awareness.permissions import ContextPermissionGuard, ObserverPermissionType
from app.context_awareness.privacy import PrivacyGuard
from app.context_awareness.proactive import ProactiveActionDispatcher
from app.context_awareness.registry import ContextRegistry
from app.context_awareness.relevance import RelevanceEngine
from app.context_awareness.scheduler import ContextScheduler
from app.context_awareness.service import ContextAwarenessService
from app.context_awareness.suggestions import SuggestionGenerator
from app.context_awareness.triggers import TriggerEngine

__all__ = [
    # Core Service
    "ContextAwarenessService",
    "ContextAwarenessConfig",
    "ContextRegistry",
    # Models
    "ActivityState",
    "TrustClassification",
    "SensitivityLevel",
    "ProactivePolicyLevel",
    "InterruptionBudgetDecision",
    "ObserverStatus",
    "TriggerType",
    "ForegroundAppInfo",
    "NotificationMetadata",
    "CalendarEvent",
    "ScheduledItem",
    "BrowserContextInfo",
    "TaskStateContext",
    "ContextSnapshot",
    "ContextTrigger",
    "ProactiveActionProposal",
    "ContextualSuggestion",
    "ContextAwarenessUIState",
    # Observers & Providers
    "BaseObserver",
    "ForegroundObserver",
    "ActivityObserver",
    "NotificationObserver",
    "CalendarObserver",
    "ContextScheduler",
    "CalendarProvider",
    "MockCalendarProvider",
    "LocalCalendarProvider",
    "NotificationProvider",
    "MockNotificationProvider",
    "LocalNotificationProvider",
    # Engines & Guards
    "PrivacyGuard",
    "ContextPermissionGuard",
    "ObserverPermissionType",
    "InterruptionManager",
    "DeduplicationManager",
    "RelevanceEngine",
    "TriggerEngine",
    "SuggestionGenerator",
    "ProactiveActionDispatcher",
    # Exceptions
    "ContextAwarenessError",
    "ObserverError",
    "ObserverPermissionError",
    "ObserverDegradedError",
    "PrivacyViolationError",
    "SensitiveContextSuppressedError",
    "TriggerError",
    "SchedulerError",
    "InterruptionBlockedError",
    "ProactivePolicyError",
    # Events
    "ContextObserverEnabledEvent",
    "ContextObserverDisabledEvent",
    "ContextObserverStatusChangedEvent",
    "ContextSnapshotCreatedEvent",
    "ContextTriggerDetectedEvent",
    "ProactiveSuggestionCreatedEvent",
    "ProactiveSuggestionSuppressedEvent",
    "ProactiveActionProposedEvent",
    "ProactiveActionRequiresConfirmationEvent",
    "ProactiveActionBlockedEvent",
    "ContextPrivacyFilterTriggeredEvent",
    "QuietHoursSuppressionEvent",
    "InterruptionCooldownEvent",
]
