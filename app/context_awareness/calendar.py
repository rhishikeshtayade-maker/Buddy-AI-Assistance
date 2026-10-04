"""BUDDY Calendar Provider & Observer Subsystem.

Calendar content is UNTRUSTED DATA, NEVER authority.
Calendar descriptions containing instructions cannot alter permissions or bypass confirmation.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional

from app.context_awareness.config import ContextAwarenessConfig
from app.context_awareness.models import (
    CalendarEvent,
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

logger = get_logger("context.calendar")


class CalendarProvider(ABC):
    """Abstract interface for external or local calendar sources."""

    @abstractmethod
    async def get_upcoming_events(self, horizon_seconds: float = 3600.0) -> List[CalendarEvent]:
        """Retrieve events starting within the horizon window."""
        raise NotImplementedError

    @abstractmethod
    async def get_event(self, event_id: str) -> Optional[CalendarEvent]:
        """Fetch a specific event by ID."""
        raise NotImplementedError

    @abstractmethod
    def health(self) -> HealthCheckResult:
        """Health status diagnostic."""
        raise NotImplementedError


class MockCalendarProvider(CalendarProvider):
    """In-memory, deterministic calendar provider for tests and local scheduling."""

    def __init__(self) -> None:
        self._events: Dict[str, CalendarEvent] = {}
        self._is_healthy: bool = True

    def add_event(
        self,
        title: str,
        start_time: float,
        end_time: Optional[float] = None,
        location: Optional[str] = None,
        description: Optional[str] = None,
        is_critical: bool = False,
    ) -> CalendarEvent:
        """Add an event to the local calendar."""
        event_id = str(uuid.uuid4())
        event = CalendarEvent(
            event_id=event_id,
            title=title,
            start_time=start_time,
            end_time=end_time,
            location=location,
            description=description,
            is_critical=is_critical,
            trust=TrustClassification.UNTRUSTED,
        )
        self._events[event_id] = event
        return event

    def remove_event(self, event_id: str) -> bool:
        return self._events.pop(event_id, None) is not None

    def clear(self) -> None:
        self._events.clear()

    def set_healthy(self, healthy: bool) -> None:
        self._is_healthy = healthy

    async def get_upcoming_events(self, horizon_seconds: float = 3600.0) -> List[CalendarEvent]:
        if not self._is_healthy:
            raise RuntimeError("Calendar provider simulated failure")
        now = time.time()
        max_time = now + horizon_seconds
        upcoming = [
            e for e in self._events.values()
            if now <= e.start_time <= max_time
        ]
        upcoming.sort(key=lambda x: x.start_time)
        return upcoming

    async def get_event(self, event_id: str) -> Optional[CalendarEvent]:
        return self._events.get(event_id)

    def health(self) -> HealthCheckResult:
        return HealthCheckResult(
            name="provider.calendar.mock",
            status=HealthStatus.HEALTHY if self._is_healthy else HealthStatus.DEGRADED,
            message="Mock calendar provider operational" if self._is_healthy else "Mock calendar provider degraded",
            timestamp=time.time(),
        )


class LocalCalendarProvider(MockCalendarProvider):
    """Local offline calendar implementation."""
    pass


class CalendarObserver(BaseObserver):
    """Periodically checks calendar providers and emits approaching event triggers."""

    def __init__(
        self,
        config: ContextAwarenessConfig,
        permission_guard: ContextPermissionGuard,
        privacy_guard: PrivacyGuard,
        provider: Optional[CalendarProvider] = None,
        event_bus: Optional[EventBus] = None,
        on_event_approaching: Optional[Callable[[CalendarEvent, TriggerType], None]] = None,
    ) -> None:
        super().__init__(
            name="calendar",
            permission_type=ObserverPermissionType.CALENDAR,
            config=config,
            permission_guard=permission_guard,
            event_bus=event_bus,
        )
        self.privacy_guard = privacy_guard
        self.provider = provider or MockCalendarProvider()
        self.on_event_approaching = on_event_approaching
        self._notified_events: Dict[str, float] = {}

    async def poll(self) -> List[CalendarEvent]:
        """Poll for events starting within next 15 minutes (900s)."""
        now = time.time()
        # Clean old notified records
        self._notified_events = {
            eid: ts for eid, ts in self._notified_events.items() if now - ts < 3600.0
        }

        events = await self.provider.get_upcoming_events(horizon_seconds=900.0)
        for ev in events:
            # Enforce untrusted
            ev.trust = TrustClassification.UNTRUSTED

            # Check if already notified
            if ev.event_id not in self._notified_events:
                self._notified_events[ev.event_id] = now
                if self.on_event_approaching:
                    try:
                        self.on_event_approaching(ev, TriggerType.CalendarEventApproaching)
                    except Exception as e:
                        logger.warning("Error in on_event_approaching callback: %s", e)

        return events
