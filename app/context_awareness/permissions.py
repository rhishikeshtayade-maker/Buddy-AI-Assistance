"""BUDDY Context Observer Permissions & Policy Guards.

Enforces fail-closed permission checks for all context observers and providers.
No hidden observer may run without explicit configuration permission.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, Set

from app.context_awareness.config import ContextAwarenessConfig
from app.context_awareness.exceptions import ObserverPermissionError


class ObserverPermissionType(str, Enum):
    """Permission capabilities required by specific observers."""

    FOREGROUND = "observer.foreground"
    ACTIVITY = "observer.activity"
    NOTIFICATIONS = "observer.notifications"
    CALENDAR = "observer.calendar"
    BROWSER = "observer.browser"
    SCHEDULER = "observer.scheduler"


class ContextPermissionGuard:
    """Evaluates whether an observer or context source is authorized to run."""

    def __init__(self, config: ContextAwarenessConfig) -> None:
        self._config = config
        self._disabled_overrides: Set[ObserverPermissionType] = set()

    def update_config(self, config: ContextAwarenessConfig) -> None:
        self._config = config

    def revoke_permission(self, permission: ObserverPermissionType) -> None:
        """Dynamically revoke permission for an observer."""
        self._disabled_overrides.add(permission)

    def restore_permission(self, permission: ObserverPermissionType) -> None:
        """Restore permission override for an observer."""
        self._disabled_overrides.discard(permission)

    def is_permitted(self, permission: ObserverPermissionType) -> bool:
        """Check if an observer permission is currently authorized."""
        # 1. Check global master switch
        if not self._config.context_awareness_enabled:
            return False

        # 2. Check explicit dynamic override
        if permission in self._disabled_overrides:
            return False

        # 3. Check individual observer config toggles
        if permission == ObserverPermissionType.FOREGROUND:
            return self._config.foreground_observer_enabled
        if permission == ObserverPermissionType.ACTIVITY:
            return self._config.activity_observer_enabled
        if permission == ObserverPermissionType.NOTIFICATIONS:
            return self._config.notification_observer_enabled
        if permission == ObserverPermissionType.CALENDAR:
            return self._config.calendar_enabled
        if permission == ObserverPermissionType.BROWSER:
            return self._config.browser_context_enabled
        if permission == ObserverPermissionType.SCHEDULER:
            return True

        return False

    def check_permission(self, permission: ObserverPermissionType, observer_name: str = "") -> None:
        """Verify permission or raise ObserverPermissionError (fail closed)."""
        if not self.is_permitted(permission):
            raise ObserverPermissionError(
                observer_name or permission.value,
                f"Permission '{permission.value}' is disabled by policy or configuration"
            )
