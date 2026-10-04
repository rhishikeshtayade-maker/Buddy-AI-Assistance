"""BUDDY Contextual Awareness & Proactive Assistance Exceptions.

Defines the typed exception hierarchy for context observers, privacy filters,
trigger evaluation, scheduling, interruption management, and proactive proposals.
"""

from __future__ import annotations

from app.core.exceptions import BuddyError


class ContextAwarenessError(BuddyError):
    """Base exception for all contextual awareness and proactive assistance errors."""


class ObserverError(ContextAwarenessError):
    """Raised when an observer encounters an operational failure."""

    def __init__(self, observer_name: str, message: str) -> None:
        self.observer_name = observer_name
        super().__init__(f"Observer '{observer_name}' error: {message}")


class ObserverPermissionError(ObserverError):
    """Raised when an observer is disabled by security policy or lacking permission."""


class ObserverDegradedError(ObserverError):
    """Raised when an observer enters a degraded state but fails gracefully."""


class PrivacyViolationError(ContextAwarenessError):
    """Raised when an operation attempts to breach the privacy boundary."""


class SensitiveContextSuppressedError(ContextAwarenessError):
    """Raised when an action is suppressed due to sensitive application context."""


class TriggerError(ContextAwarenessError):
    """Raised when a contextual trigger fails evaluation or validation."""


class SchedulerError(ContextAwarenessError):
    """Raised when a scheduling operation or cron evaluation fails."""


class InterruptionBlockedError(ContextAwarenessError):
    """Raised when proactive assistance is blocked by quiet hours or interruption budget."""


class ProactivePolicyError(ContextAwarenessError):
    """Raised when a proactive proposal violates security policy."""
