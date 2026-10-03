"""BUDDY Health Monitoring Subsystem.

Provides health checks, latency measurement, system-wide health aggregation,
and status change notifications.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

import psutil


class HealthStatus(str, Enum):
    """Health check status levels."""

    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


@dataclass(frozen=True)
class HealthCheckResult:
    """Diagnostic outcome of an individual component health check."""

    name: str
    status: HealthStatus
    message: str
    timestamp: float = field(default_factory=time.time)
    latency: float = 0.0  # Latency in seconds
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SystemHealthResult:
    """Aggregated health outcome for the entire BUDDY system."""

    status: HealthStatus
    checks: Dict[str, HealthCheckResult]
    timestamp: float = field(default_factory=time.time)
    message: str = "System health evaluated"


HealthCheckFn = Callable[[], Union[HealthCheckResult, Coroutine[Any, Any, HealthCheckResult]]]


class HealthManager:
    """Manages component health checks, executes diagnostics, and calculates system health."""

    def __init__(self) -> None:
        self._checks: Dict[str, HealthCheckFn] = {}

    def register_check(self, name: str, check_fn: HealthCheckFn) -> None:
        """Register a diagnostic check function."""
        if not callable(check_fn):
            raise TypeError(f"Health check '{name}' must be callable")
        self._checks[name] = check_fn

    def unregister_check(self, name: str) -> bool:
        """Unregister a diagnostic check."""
        return self._checks.pop(name, None) is not None

    @staticmethod
    def calculate_overall_health(results: List[HealthCheckResult]) -> HealthStatus:
        """Aggregate health status: UNHEALTHY takes priority, then DEGRADED, else HEALTHY."""
        if not results:
            return HealthStatus.HEALTHY

        if any(r.status == HealthStatus.UNHEALTHY for r in results):
            return HealthStatus.UNHEALTHY
        if any(r.status == HealthStatus.DEGRADED for r in results):
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY

    async def run_check(self, name: str) -> HealthCheckResult:
        """Execute a single named health check measuring elapsed latency."""
        check_fn = self._checks.get(name)
        if not check_fn:
            return HealthCheckResult(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=f"Check '{name}' is not registered",
                timestamp=time.time(),
                latency=0.0,
            )

        start_time = time.perf_counter()
        try:
            if inspect.iscoroutinefunction(check_fn):
                result = await check_fn()
            else:
                result = check_fn()
                if inspect.iscoroutine(result):
                    result = await result

            latency = time.perf_counter() - start_time
            if not isinstance(result, HealthCheckResult):
                return HealthCheckResult(
                    name=name,
                    status=HealthStatus.DEGRADED,
                    message=f"Check returned unexpected type: {type(result)}",
                    timestamp=time.time(),
                    latency=latency,
                )

            # Preserve measured latency if not populated
            if result.latency == 0.0:
                return HealthCheckResult(
                    name=result.name,
                    status=result.status,
                    message=result.message,
                    timestamp=result.timestamp,
                    latency=latency,
                    details=result.details,
                )
            return result

        except Exception as err:
            latency = time.perf_counter() - start_time
            return HealthCheckResult(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=f"Health check failed with error: {err}",
                timestamp=time.time(),
                latency=latency,
                details={"error": str(err)},
            )

    async def run_all_checks(self) -> SystemHealthResult:
        """Execute all registered health checks concurrently and aggregate system status."""
        results: Dict[str, HealthCheckResult] = {}

        if not self._checks:
            return SystemHealthResult(
                status=HealthStatus.HEALTHY,
                checks={},
                timestamp=time.time(),
                message="No health checks registered",
            )

        # Run checks concurrently
        check_tasks = [self.run_check(name) for name in self._checks]
        completed = await asyncio.gather(*check_tasks)

        for res in completed:
            results[res.name] = res

        overall = self.calculate_overall_health(list(results.values()))
        return SystemHealthResult(
            status=overall,
            checks=results,
            timestamp=time.time(),
            message=f"Overall status: {overall.value}",
        )


# ---------------------------------------------------------------------------
# Standard Built-In Core Health Checks
# ---------------------------------------------------------------------------


def create_config_health_check(config_service: Any) -> HealthCheckFn:
    """Produce health check verifying configuration integrity."""

    def _check() -> HealthCheckResult:
        if config_service is None:
            return HealthCheckResult(
                name="configuration",
                status=HealthStatus.UNHEALTHY,
                message="Configuration service is None",
            )
        if not hasattr(config_service, "app_env") or not hasattr(config_service, "log_level"):
            return HealthCheckResult(
                name="configuration",
                status=HealthStatus.DEGRADED,
                message="Configuration is missing standard fields",
            )
        return HealthCheckResult(
            name="configuration",
            status=HealthStatus.HEALTHY,
            message=f"Config loaded (env={config_service.app_env})",
            details={"env": config_service.app_env, "log_level": config_service.log_level},
        )

    return _check


def create_event_bus_health_check(event_bus_service: Any) -> HealthCheckFn:
    """Produce health check verifying event bus activity."""

    def _check() -> HealthCheckResult:
        if event_bus_service is None:
            return HealthCheckResult(
                name="event_bus",
                status=HealthStatus.UNHEALTHY,
                message="EventBus service is None",
            )
        if not getattr(event_bus_service, "is_active", False):
            return HealthCheckResult(
                name="event_bus",
                status=HealthStatus.UNHEALTHY,
                message="EventBus is inactive or stopped",
            )
        return HealthCheckResult(
            name="event_bus",
            status=HealthStatus.HEALTHY,
            message="EventBus is active and responsive",
        )

    return _check


def create_service_registry_health_check(registry_service: Any) -> HealthCheckFn:
    """Produce health check verifying service registry status."""

    def _check() -> HealthCheckResult:
        if registry_service is None:
            return HealthCheckResult(
                name="service_registry",
                status=HealthStatus.UNHEALTHY,
                message="Service registry is None",
            )
        services = registry_service.list_services()
        if not services:
            return HealthCheckResult(
                name="service_registry",
                status=HealthStatus.DEGRADED,
                message="Service registry is empty",
            )
        return HealthCheckResult(
            name="service_registry",
            status=HealthStatus.HEALTHY,
            message=f"Service registry contains {len(services)} services",
            details={"registered_services": services},
        )

    return _check


def create_runtime_health_check() -> HealthCheckFn:
    """Produce health check verifying system platform, python version, and memory."""

    def _check() -> HealthCheckResult:
        try:
            mem = psutil.virtual_memory()
            mem_percent = mem.percent
            status = HealthStatus.HEALTHY
            message = f"Python {sys.version.split()[0]} on {sys.platform} | RAM {mem_percent}%"

            if mem_percent > 95.0:
                status = HealthStatus.DEGRADED
                message = f"High RAM usage: {mem_percent}%"

            return HealthCheckResult(
                name="runtime",
                status=status,
                message=message,
                details={
                    "platform": sys.platform,
                    "python_version": sys.version.split()[0],
                    "ram_usage_percent": mem_percent,
                },
            )
        except Exception as e:
            return HealthCheckResult(
                name="runtime",
                status=HealthStatus.DEGRADED,
                message=f"Runtime inspection limited: {e}",
            )

    return _check
