"""BUDDY User Activity Observer.

Monitors coarse user activity state (ACTIVE, IDLE, AWAY, UNKNOWN) using
safe OS inactivity duration timers without any behavioral surveillance.

STRICT PRIVACY GUARANTEES:
- NO keystroke logging
- NO mouse tracking or trajectory recording
- NO clipboard monitoring
- NO typed content inspection
- Only coarse inactivity duration is evaluated
"""

from __future__ import annotations

import ctypes
import sys
import time
from typing import Callable, Optional

from app.context_awareness.config import ContextAwarenessConfig
from app.context_awareness.models import ActivityState, TriggerType
from app.context_awareness.observers import BaseObserver
from app.context_awareness.permissions import ContextPermissionGuard, ObserverPermissionType
from app.core.events import EventBus
from app.core.logging import get_logger

logger = get_logger("context.activity")


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("dwTime", ctypes.c_ulong),
    ]


class ActivityObserver(BaseObserver):
    """Monitors system-wide idle duration to derive coarse activity state."""

    def __init__(
        self,
        config: ContextAwarenessConfig,
        permission_guard: ContextPermissionGuard,
        event_bus: Optional[EventBus] = None,
        on_activity_change: Optional[Callable[[ActivityState, TriggerType], None]] = None,
    ) -> None:
        super().__init__(
            name="activity",
            permission_type=ObserverPermissionType.ACTIVITY,
            config=config,
            permission_guard=permission_guard,
            event_bus=event_bus,
        )
        self.on_activity_change = on_activity_change
        self._current_state: ActivityState = ActivityState.UNKNOWN
        self._simulated_idle_seconds: Optional[float] = None

    @property
    def current_state(self) -> ActivityState:
        return self._current_state

    def set_simulated_idle_seconds(self, seconds: float) -> None:
        """Testing utility: simulate an exact elapsed idle duration."""
        self._simulated_idle_seconds = seconds

    def clear_simulated_idle(self) -> None:
        """Clear test simulation."""
        self._simulated_idle_seconds = None

    def _get_idle_seconds_windows(self) -> float:
        """Retrieve system inactivity duration in seconds via GetLastInputInfo."""
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            return max(0.0, millis / 1000.0)
        return 0.0

    def get_inactivity_seconds(self) -> float:
        """Determine inactivity duration in seconds."""
        if self._simulated_idle_seconds is not None:
            return self._simulated_idle_seconds

        if sys.platform == "win32":
            try:
                return self._get_idle_seconds_windows()
            except Exception as e:
                logger.debug("Win32 GetLastInputInfo failed: %s", e)

        # Default fallback: 0 seconds (active)
        return 0.0

    def evaluate_state(self, idle_seconds: float) -> ActivityState:
        """Classify inactivity seconds into coarse ActivityState."""
        if idle_seconds >= self.config.activity_away_threshold:
            return ActivityState.AWAY
        if idle_seconds >= self.config.activity_idle_threshold:
            return ActivityState.IDLE
        return ActivityState.ACTIVE

    async def poll(self) -> ActivityState:
        """Poll inactivity and detect transitions."""
        idle_seconds = self.get_inactivity_seconds()
        new_state = self.evaluate_state(idle_seconds)
        prev_state = self._current_state
        self._current_state = new_state

        if prev_state != new_state:
            trigger_type = (
                TriggerType.UserBecameIdle
                if new_state in (ActivityState.IDLE, ActivityState.AWAY)
                else TriggerType.UserBecameActive
            )
            if self.on_activity_change:
                try:
                    self.on_activity_change(new_state, trigger_type)
                except Exception as e:
                    logger.warning("Error in on_activity_change callback: %s", e)

        return new_state
