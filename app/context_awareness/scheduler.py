"""BUDDY Contextual Scheduler.

Manages one-time, recurring, and relative scheduled items.
Emits ScheduledTimeReached triggers to the trigger engine.

CRITICAL SECURITY REQUIREMENT:
Scheduled items are context triggers, NOT OS cron execution commands.
All resulting actions must pass through ToolRegistry and ToolExecutor.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from app.context_awareness.config import ContextAwarenessConfig
from app.context_awareness.exceptions import SchedulerError
from app.context_awareness.models import (
    ObserverStatus,
    ScheduledItem,
    TriggerType,
)
from app.context_awareness.observers import BaseObserver
from app.context_awareness.permissions import ContextPermissionGuard, ObserverPermissionType
from app.core.events import EventBus
from app.core.health import HealthCheckResult, HealthStatus
from app.core.logging import get_logger

logger = get_logger("context.scheduler")


class ContextScheduler(BaseObserver):
    """Contextual time-based scheduler with cancellation, recurrence, and event windows."""

    def __init__(
        self,
        config: ContextAwarenessConfig,
        permission_guard: ContextPermissionGuard,
        event_bus: Optional[EventBus] = None,
        on_schedule_reached: Optional[Callable[[ScheduledItem, TriggerType], None]] = None,
    ) -> None:
        super().__init__(
            name="scheduler",
            permission_type=ObserverPermissionType.SCHEDULER,
            config=config,
            permission_guard=permission_guard,
            event_bus=event_bus,
        )
        self.on_schedule_reached = on_schedule_reached
        self._items: Dict[str, ScheduledItem] = {}
        self._missed_tolerance_seconds: float = 300.0  # 5 min window for missed events

    def schedule_once(
        self,
        name: str,
        target_time: float,
        payload: Optional[Dict[str, Any]] = None,
        is_critical: bool = False,
    ) -> ScheduledItem:
        """Schedule a one-off event at a specific unix timestamp."""
        item_id = str(uuid.uuid4())
        item = ScheduledItem(
            item_id=item_id,
            name=name,
            target_time=target_time,
            payload=payload or {},
            is_critical=is_critical,
        )
        self._items[item_id] = item
        logger.info("Scheduled item '%s' for timestamp %f", name, target_time)
        return item

    def schedule_recurring(
        self,
        name: str,
        interval_seconds: float,
        payload: Optional[Dict[str, Any]] = None,
        is_critical: bool = False,
        start_delay: float = 0.0,
    ) -> ScheduledItem:
        """Schedule a recurring event at fixed intervals."""
        if interval_seconds <= 0:
            raise SchedulerError("Recurring interval must be greater than zero")

        item_id = str(uuid.uuid4())
        target_time = time.time() + (start_delay if start_delay > 0 else interval_seconds)
        item = ScheduledItem(
            item_id=item_id,
            name=name,
            target_time=target_time,
            recurring_interval_seconds=interval_seconds,
            payload=payload or {},
            is_critical=is_critical,
        )
        self._items[item_id] = item
        logger.info("Scheduled recurring item '%s' every %fs", name, interval_seconds)
        return item

    def schedule_relative(
        self,
        name: str,
        base_time: float,
        offset_seconds: float,
        payload: Optional[Dict[str, Any]] = None,
        is_critical: bool = False,
    ) -> ScheduledItem:
        """Schedule an item relative to another timestamp (e.g. 10m before base_time: offset = -600)."""
        target_time = base_time + offset_seconds
        return self.schedule_once(
            name=name,
            target_time=target_time,
            payload=payload,
            is_critical=is_critical,
        )

    def cancel(self, item_id: str) -> bool:
        """Cancel an active scheduled item."""
        item = self._items.get(item_id)
        if item:
            item.cancelled = True
            self._items.pop(item_id, None)
            logger.info("Cancelled scheduled item '%s' (%s)", item.name, item_id)
            return True
        return False

    def get_item(self, item_id: str) -> Optional[ScheduledItem]:
        return self._items.get(item_id)

    def list_items(self) -> List[ScheduledItem]:
        return [i for i in self._items.values() if not i.cancelled]

    def clear(self) -> None:
        self._items.clear()

    async def poll(self) -> List[ScheduledItem]:
        """Evaluate pending items, fire triggers, and reschedule recurring items."""
        now = time.time()
        due_items: List[ScheduledItem] = []

        for item_id, item in list(self._items.items()):
            if item.cancelled:
                self._items.pop(item_id, None)
                continue

            # Check if due
            if item.target_time <= now:
                # Check missed-event tolerance
                if now - item.target_time <= self._missed_tolerance_seconds:
                    due_items.append(item)
                else:
                    logger.warning("Scheduled item '%s' missed deadline window (stale)", item.name)

                # Reschedule if recurring
                if item.recurring_interval_seconds and item.recurring_interval_seconds > 0:
                    item.target_time = now + item.recurring_interval_seconds
                else:
                    self._items.pop(item_id, None)

        # Trigger callbacks
        for item in due_items:
            if self.on_schedule_reached:
                try:
                    self.on_schedule_reached(item, TriggerType.ScheduledTimeReached)
                except Exception as e:
                    logger.warning("Error in on_schedule_reached callback: %s", e)

        return due_items
