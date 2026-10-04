"""BUDDY Base Observer Interface & Failure Isolation.

Provides abstract base class for all context observers with lifecycle controls,
asynchronous polling, exception isolation, and health diagnostics.
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Coroutine, Dict, Optional

from app.context_awareness.config import ContextAwarenessConfig
from app.context_awareness.exceptions import ObserverError
from app.context_awareness.models import ObserverStatus
from app.context_awareness.permissions import ContextPermissionGuard, ObserverPermissionType
from app.core.events import EventBus
from app.core.health import HealthCheckResult, HealthStatus
from app.core.logging import get_logger

logger = get_logger("context.observers")


class BaseObserver(ABC):
    """Abstract base observer supporting lifecycle, health checks, and failure isolation."""

    def __init__(
        self,
        name: str,
        permission_type: ObserverPermissionType,
        config: ContextAwarenessConfig,
        permission_guard: ContextPermissionGuard,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self.name = name
        self.permission_type = permission_type
        self.config = config
        self.permission_guard = permission_guard
        self.event_bus = event_bus

        self._status: ObserverStatus = ObserverStatus.DISABLED
        self._is_running: bool = False
        self._task: Optional[asyncio.Task[None]] = None
        self._last_error: Optional[str] = None
        self._last_poll_time: float = 0.0

    @property
    def status(self) -> ObserverStatus:
        return self._status

    @property
    def is_running(self) -> bool:
        return self._is_running

    def is_permitted(self) -> bool:
        return self.permission_guard.is_permitted(self.permission_type)

    async def start(self) -> None:
        """Start the observer loop. Idempotent. Fails gracefully if not permitted."""
        if self._is_running:
            return

        if not self.is_permitted():
            self._status = ObserverStatus.DISABLED
            logger.info("Observer '%s' is disabled by policy/config.", self.name)
            return

        self._is_running = True
        self._status = ObserverStatus.HEALTHY
        self._last_error = None
        self._task = asyncio.create_task(self._run_loop(), name=f"observer_{self.name}")
        logger.info("Observer '%s' started.", self.name)

    async def stop(self) -> None:
        """Stop the observer gracefully."""
        self._is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._status = ObserverStatus.DISABLED
        logger.info("Observer '%s' stopped.", self.name)

    async def cancel(self) -> None:
        """Immediately cancel background observer task."""
        await self.stop()

    async def _run_loop(self) -> None:
        """Continuous polling loop with failure isolation."""
        while self._is_running:
            try:
                if not self.is_permitted():
                    self._status = ObserverStatus.DISABLED
                    break

                poll_start = time.perf_counter()
                await self.poll()
                self._last_poll_time = time.time()
                self._status = ObserverStatus.HEALTHY

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._status = ObserverStatus.DEGRADED
                self._last_error = str(exc)
                logger.warning(
                    "Observer '%s' encountered an error (isolated, runtime unaffected): %s",
                    self.name,
                    exc,
                )

            # Bounded sleep interval
            try:
                await asyncio.sleep(self.config.observer_poll_interval_seconds)
            except asyncio.CancelledError:
                break

    @abstractmethod
    async def poll(self) -> Any:
        """Execute one polling iteration. Subclasses must implement."""
        raise NotImplementedError

    def health(self) -> HealthCheckResult:
        """Produce standard health diagnostic for HealthManager."""
        health_status = (
            HealthStatus.HEALTHY
            if self._status == ObserverStatus.HEALTHY
            else HealthStatus.DEGRADED
            if self._status == ObserverStatus.DEGRADED
            else HealthStatus.HEALTHY
        )
        msg = f"Observer {self.name} is {self._status.value}"
        if self._last_error:
            msg += f" (last error: {self._last_error})"

        return HealthCheckResult(
            name=f"observer.{self.name}",
            status=health_status,
            message=msg,
            timestamp=time.time(),
            latency=0.0,
            details={
                "status": self._status.value,
                "is_running": self._is_running,
                "last_poll_time": self._last_poll_time,
                "permitted": self.is_permitted(),
            },
        )
