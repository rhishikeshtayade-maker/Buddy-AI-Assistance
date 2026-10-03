"""Unit tests for BUDDY Health Check Framework."""

import asyncio
import unittest
from app.core import (
    BuddyConfig,
    EventBus,
    HealthCheckResult,
    HealthManager,
    HealthStatus,
    ServiceRegistry,
    SystemHealthResult,
)
from app.core.health import (
    create_config_health_check,
    create_event_bus_health_check,
    create_runtime_health_check,
    create_service_registry_health_check,
)


class TestHealthManager(unittest.IsolatedAsyncioTestCase):
    """Test suite verifying health check registration, execution, and calculation."""

    async def asyncSetUp(self) -> None:
        self.health_mgr = HealthManager()

    def test_overall_health_calculation(self) -> None:
        """Verify priority rules: UNHEALTHY > DEGRADED > HEALTHY."""
        h_ok = HealthCheckResult("ok", HealthStatus.HEALTHY, "all good")
        h_deg = HealthCheckResult("deg", HealthStatus.DEGRADED, "warning")
        h_bad = HealthCheckResult("bad", HealthStatus.UNHEALTHY, "critical failure")

        # All healthy -> HEALTHY
        self.assertEqual(
            self.health_mgr.calculate_overall_health([h_ok]),
            HealthStatus.HEALTHY,
        )

        # Healthy + Degraded -> DEGRADED
        self.assertEqual(
            self.health_mgr.calculate_overall_health([h_ok, h_deg]),
            HealthStatus.DEGRADED,
        )

        # Degraded + Unhealthy -> UNHEALTHY
        self.assertEqual(
            self.health_mgr.calculate_overall_health([h_deg, h_bad]),
            HealthStatus.UNHEALTHY,
        )

        # All -> UNHEALTHY
        self.assertEqual(
            self.health_mgr.calculate_overall_health([h_ok, h_deg, h_bad]),
            HealthStatus.UNHEALTHY,
        )

    async def test_run_check_measures_latency_and_handles_exception(self) -> None:
        """Verify health check records elapsed latency and converts unhandled exceptions to UNHEALTHY."""
        async def slow_failing_check() -> HealthCheckResult:
            await asyncio.sleep(0.01)
            raise ValueError("Database connection refused")

        self.health_mgr.register_check("db", slow_failing_check)
        res = await self.health_mgr.run_check("db")

        self.assertEqual(res.status, HealthStatus.UNHEALTHY)
        self.assertIn("Database connection refused", res.message)
        self.assertGreaterEqual(res.latency, 0.01)

    async def test_built_in_health_checks(self) -> None:
        """Verify built-in checks for config, event bus, registry, and runtime."""
        config = BuddyConfig()
        event_bus = EventBus()
        registry = ServiceRegistry()
        registry.register("service_1", 100)

        self.health_mgr.register_check("configuration", create_config_health_check(config))
        self.health_mgr.register_check("event_bus", create_event_bus_health_check(event_bus))
        self.health_mgr.register_check("service_registry", create_service_registry_health_check(registry))
        self.health_mgr.register_check("runtime", create_runtime_health_check())

        system_report = await self.health_mgr.run_all_checks()
        self.assertEqual(system_report.status, HealthStatus.HEALTHY)
        self.assertIn("configuration", system_report.checks)
        self.assertIn("event_bus", system_report.checks)
        self.assertIn("service_registry", system_report.checks)
        self.assertIn("runtime", system_report.checks)


if __name__ == "__main__":
    unittest.main()
