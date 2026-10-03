"""BUDDY Core Event Bus and Event Definitions.

Provides a lightweight, asynchronous, decoupled publish-subscribe event bus
with subscriber isolation, type-safe event dispatch, and clean lifecycle management.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
    Type,
    TypeVar,
    Union,
)

from app.core.state import BuddyState

logger = logging.getLogger("buddy.core.events")

# ---------------------------------------------------------------------------
# Base Event & Core Event Definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BaseEvent:
    """Base class for all typed BUDDY events."""

    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass(frozen=True)
class ApplicationStartedEvent(BaseEvent):
    """Emitted when the BUDDY core runtime finishes initialization and enters IDLE."""

    app_name: str = "BUDDY"
    version: str = "0.1.0"
    environment: str = "development"


@dataclass(frozen=True)
class ApplicationStoppingEvent(BaseEvent):
    """Emitted when BUDDY initiates graceful shutdown."""

    reason: str = "Graceful shutdown requested"


@dataclass(frozen=True)
class ApplicationStoppedEvent(BaseEvent):
    """Emitted after BUDDY completes cleanup and shuts down all services."""

    exit_code: int = 0


@dataclass(frozen=True)
class StateChangedEvent(BaseEvent):
    """Emitted on every validated state transition.

    Contains previous state, new state, timestamp, and reason.
    No secrets or sensitive user data are included.
    """

    previous_state: BuddyState = BuddyState.STARTING
    new_state: BuddyState = BuddyState.IDLE
    reason: str = "State transitioned"


@dataclass(frozen=True)
class ErrorEvent(BaseEvent):
    """Emitted whenever a recoverable or fatal error occurs across the runtime."""

    error_type: str = "RuntimeError"
    message: str = "An error occurred"
    state: Optional[BuddyState] = None
    fatal: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HealthChangedEvent(BaseEvent):
    """Emitted when a health check or system-wide health status changes."""

    component: str = "system"
    previous_status: str = "HEALTHY"
    new_status: str = "HEALTHY"
    message: str = "Status updated"


TEvent = TypeVar("TEvent", bound=BaseEvent)
EventHandler = Callable[[Any], Union[Coroutine[Any, Any, None], None]]


# ---------------------------------------------------------------------------
# Async Event Bus Implementation
# ---------------------------------------------------------------------------


class EventBus:
    """Lightweight asynchronous event bus with isolation and type dispatch."""

    def __init__(self) -> None:
        self._subscribers: Dict[Type[BaseEvent], List[EventHandler]] = {}
        self._any_subscribers: List[EventHandler] = []
        self._is_active: bool = True
        self._lock = asyncio.Lock()

    @property
    def is_active(self) -> bool:
        """Return whether the event bus is currently active."""
        return self._is_active

    def subscribe(
        self,
        event_type: Optional[Type[TEvent]],
        handler: EventHandler,
    ) -> None:
        """Subscribe a callable or coroutine function to events of event_type.

        If event_type is None, handler subscribes to all events (wildcard).
        """
        if not callable(handler):
            raise TypeError("Event handler must be callable")

        if event_type is None:
            if handler not in self._any_subscribers:
                self._any_subscribers.append(handler)
            return

        if not isinstance(event_type, type) or not issubclass(event_type, BaseEvent):
            raise TypeError(f"Invalid event type: {event_type}. Must inherit from BaseEvent.")

        if event_type not in self._subscribers:
            self._subscribers[event_type] = []

        if handler not in self._subscribers[event_type]:
            self._subscribers[event_type].append(handler)

    def unsubscribe(
        self,
        event_type: Optional[Type[TEvent]],
        handler: EventHandler,
    ) -> bool:
        """Unsubscribe handler from event_type.

        Returns True if removed, False if not present.
        """
        if event_type is None:
            if handler in self._any_subscribers:
                self._any_subscribers.remove(handler)
                return True
            return False

        if event_type in self._subscribers and handler in self._subscribers[event_type]:
            self._subscribers[event_type].remove(handler)
            if not self._subscribers[event_type]:
                del self._subscribers[event_type]
            return True
        return False

    async def publish(self, event: BaseEvent) -> None:
        """Publish an event to all registered subscribers.

        Each subscriber is executed in deterministic order.
        Exception isolation guarantees one failing handler does not crash others.
        """
        if not self._is_active:
            logger.warning("EventBus is stopped; ignoring event: %s", type(event).__name__)
            return

        if not isinstance(event, BaseEvent):
            raise TypeError(f"Published event must inherit from BaseEvent, got {type(event)}")

        # Collect relevant handlers
        handlers: List[EventHandler] = []

        # Subscribed to exact type or any superclass of the event
        for subscribed_cls, sub_handlers in list(self._subscribers.items()):
            if isinstance(event, subscribed_cls):
                handlers.extend(sub_handlers)

        # Global subscribers
        handlers.extend(self._any_subscribers)

        for handler in handlers:
            try:
                if inspect.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    res = handler(event)
                    if inspect.iscoroutine(res):
                        await res
            except Exception as err:
                logger.error(
                    "Event handler '%s' failed for event '%s': %s",
                    getattr(handler, "__name__", str(handler)),
                    type(event).__name__,
                    err,
                    exc_info=True,
                )

    def publish_sync(self, event: BaseEvent) -> None:
        """Synchronously schedule or dispatch an event.

        If an asyncio loop is running in the current thread, schedules it as a task.
        Otherwise creates a temporary event loop to dispatch.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.publish(event))
        except RuntimeError:
            asyncio.run(self.publish(event))

    async def shutdown(self) -> None:
        """Shut down the event bus and clear all subscriptions."""
        self._is_active = False
        self._subscribers.clear()
        self._any_subscribers.clear()
        logger.debug("EventBus shut down and cleared.")
