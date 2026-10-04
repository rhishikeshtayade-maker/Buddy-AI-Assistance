"""BUDDY Notification Observer & Provider Subsystem.

Treats OS and application notifications as UNTRUSTED EXTERNAL CONTENT.
Notification data MUST NEVER become execution instructions or alter security policies.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from typing import Callable, List, Optional

from app.context_awareness.config import ContextAwarenessConfig
from app.context_awareness.models import (
    NotificationMetadata,
    SensitivityLevel,
    TriggerType,
    TrustClassification,
)
from app.context_awareness.observers import BaseObserver
from app.context_awareness.permissions import ContextPermissionGuard, ObserverPermissionType
from app.context_awareness.privacy import PrivacyGuard
from app.core.events import EventBus
from app.core.health import HealthCheckResult, HealthStatus
from app.core.logging import get_logger

logger = get_logger("context.notifications")


class NotificationProvider(ABC):
    """Abstract provider interface for system and app notifications."""

    @abstractmethod
    async def get_recent_notifications(self, since_timestamp: float) -> List[NotificationMetadata]:
        """Fetch notifications received since the given timestamp."""
        raise NotImplementedError

    @abstractmethod
    def health(self) -> HealthCheckResult:
        """Health status of the notification provider."""
        raise NotImplementedError


class MockNotificationProvider(NotificationProvider):
    """Deterministic, in-memory notification provider for testing and environments without OS hooks."""

    def __init__(self) -> None:
        self._notifications: List[NotificationMetadata] = []
        self._is_healthy: bool = True

    def post_notification(
        self,
        source_app: str,
        title: Optional[str] = None,
        preview: Optional[str] = None,
        sensitivity: SensitivityLevel = SensitivityLevel.SAFE,
    ) -> NotificationMetadata:
        """Inject a test or mock notification."""
        notif = NotificationMetadata(
            source_app=source_app,
            title=title,
            preview=preview,
            sensitivity=sensitivity,
            trust=TrustClassification.UNTRUSTED,
            timestamp=time.time(),
        )
        self._notifications.append(notif)
        return notif

    def set_healthy(self, healthy: bool) -> None:
        self._is_healthy = healthy

    async def get_recent_notifications(self, since_timestamp: float) -> List[NotificationMetadata]:
        return [n for n in self._notifications if n.timestamp > since_timestamp]

    def health(self) -> HealthCheckResult:
        return HealthCheckResult(
            name="provider.notification.mock",
            status=HealthStatus.HEALTHY if self._is_healthy else HealthStatus.UNHEALTHY,
            message="Mock notification provider operational" if self._is_healthy else "Mock provider degraded",
            timestamp=time.time(),
        )


class LocalNotificationProvider(MockNotificationProvider):
    """Standard local provider implementation for desktop environments."""
    pass


class NotificationObserver(BaseObserver):
    """Monitors incoming notifications from providers, applying privacy filters and untrusted flags."""

    def __init__(
        self,
        config: ContextAwarenessConfig,
        permission_guard: ContextPermissionGuard,
        privacy_guard: PrivacyGuard,
        provider: Optional[NotificationProvider] = None,
        event_bus: Optional[EventBus] = None,
        on_notification: Optional[Callable[[NotificationMetadata, TriggerType], None]] = None,
    ) -> None:
        super().__init__(
            name="notifications",
            permission_type=ObserverPermissionType.NOTIFICATIONS,
            config=config,
            permission_guard=permission_guard,
            event_bus=event_bus,
        )
        self.privacy_guard = privacy_guard
        self.provider = provider or MockNotificationProvider()
        self.on_notification = on_notification
        self._last_checked_time: float = time.time()

    async def poll(self) -> List[NotificationMetadata]:
        """Poll for new notifications since last poll."""
        now = time.time()
        notifications = await self.provider.get_recent_notifications(self._last_checked_time)
        self._last_checked_time = now

        for n in notifications:
            # Enforce untrusted classification
            n.trust = TrustClassification.UNTRUSTED

            # Check privacy & sensitivity
            is_sensitive = self.privacy_guard.is_sensitive_context(
                window_title=n.title,
            ) or (n.preview and self.privacy_guard.is_sensitive_context(window_title=n.preview))

            if is_sensitive:
                n.sensitivity = SensitivityLevel.HIGHLY_SENSITIVE
                n.preview = None
                n.title = "[REDACTED_NOTIFICATION]"

            if self.on_notification:
                try:
                    self.on_notification(n, TriggerType.NotificationReceived)
                except Exception as e:
                    logger.warning("Error in on_notification callback: %s", e)

        return notifications
