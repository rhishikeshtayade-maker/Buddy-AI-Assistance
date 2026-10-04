"""BUDDY Context Observer & Provider Registry.

Manages registered observers, providers, and contextual trigger handlers.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.context_awareness.calendar import CalendarProvider
from app.context_awareness.notifications import NotificationProvider
from app.context_awareness.observers import BaseObserver
from app.core.logging import get_logger

logger = get_logger("context.registry")


class ContextRegistry:
    """Registry maintaining active observers, calendar providers, and notification providers."""

    def __init__(self) -> None:
        self._observers: Dict[str, BaseObserver] = {}
        self._calendar_providers: Dict[str, CalendarProvider] = {}
        self._notification_providers: Dict[str, NotificationProvider] = {}

    def register_observer(self, observer: BaseObserver) -> None:
        """Register an observer instance."""
        self._observers[observer.name] = observer
        logger.debug("Registered observer: %s", observer.name)

    def unregister_observer(self, name: str) -> Optional[BaseObserver]:
        return self._observers.pop(name, None)

    def get_observer(self, name: str) -> Optional[BaseObserver]:
        return self._observers.get(name)

    def list_observers(self) -> List[BaseObserver]:
        return list(self._observers.values())

    def register_calendar_provider(self, name: str, provider: CalendarProvider) -> None:
        self._calendar_providers[name] = provider

    def get_calendar_provider(self, name: str = "default") -> Optional[CalendarProvider]:
        return self._calendar_providers.get(name) or next(iter(self._calendar_providers.values()), None)

    def register_notification_provider(self, name: str, provider: NotificationProvider) -> None:
        self._notification_providers[name] = provider

    def get_notification_provider(self, name: str = "default") -> Optional[NotificationProvider]:
        return self._notification_providers.get(name) or next(iter(self._notification_providers.values()), None)
