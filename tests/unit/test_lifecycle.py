"""Unit tests for BUDDY Application Lifecycle Manager and Error Handling."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.core import (
    ApplicationStartedEvent,
    ApplicationStoppedEvent,
    ApplicationStoppingEvent,
    BuddyConfig,
    BuddyState,
    ErrorEvent,
    HealthCheckResult,
    HealthStatus,
    LifecycleError,
    LifecycleManager,
    StateChangedEvent,
)


class TestLifecycleManager(unittest.IsolatedAsyncioTestCase):
    """Test suite verifying lifecycle sequencing, error handling, and shutdown idempotency."""

    async def asyncSetUp(self) -> None:
        self.config = BuddyConfig(app_env="testing", log_level="DEBUG")
        self.lifecycle = LifecycleManager(self.config)

    async def asyncTearDown(self) -> None:
        await self.lifecycle.shutdown()

    async def test_initialization_and_start_flow(self) -> None:
        """Verify normal flow: STARTING -> initialize() -> start() -> IDLE."""
        self.assertEqual(self.lifecycle.state_machine.current_state, BuddyState.STARTING)

        ctx = await self.lifecycle.initialize()
        self.assertIsNotNone(ctx)
        self.assertEqual(self.lifecycle.state_machine.current_state, BuddyState.STARTING)

        health_report = await self.lifecycle.start()
        self.assertEqual(health_report.status, HealthStatus.HEALTHY)
        self.assertEqual(self.lifecycle.state_machine.current_state, BuddyState.IDLE)
        self.assertTrue(self.lifecycle.is_running)

    async def test_lifecycle_events_emitted(self) -> None:
        """Verify ApplicationStartedEvent, StateChangedEvent, ApplicationStoppingEvent are emitted."""
        events_received = []

        async def capture_event(ev):
            events_received.append(ev)

        self.lifecycle.event_bus.subscribe(None, capture_event)

        await self.lifecycle.initialize()
        await self.lifecycle.start()
        await self.lifecycle.shutdown(reason="Test shutdown")

        event_types = [type(e) for e in events_received]
        self.assertIn(ApplicationStartedEvent, event_types)
        self.assertIn(StateChangedEvent, event_types)
        self.assertIn(ApplicationStoppingEvent, event_types)

    async def test_startup_health_failure_halts_start(self) -> None:
        """Verify that an UNHEALTHY system check during start() raises LifecycleError."""
        await self.lifecycle.initialize()

        # Inject an unhealthy check
        async def unhealthy_check():
            return HealthCheckResult("bad_service", HealthStatus.UNHEALTHY, "Critical mock failure")

        self.lifecycle.health_manager.register_check("bad_service", unhealthy_check)

        with self.assertRaises(LifecycleError):
            await self.lifecycle.start()

        # It transitioned to ERROR and then SHUTTING_DOWN during fatal startup failure
        states_in_history = [rec.new_state for rec in self.lifecycle.state_machine.history]
        self.assertIn(BuddyState.ERROR, states_in_history)
        self.assertEqual(self.lifecycle.state_machine.current_state, BuddyState.SHUTTING_DOWN)

    async def test_shutdown_is_idempotent(self) -> None:
        """Verify calling shutdown multiple times does not crash or raise errors."""
        await self.lifecycle.initialize()
        await self.lifecycle.start()

        await self.lifecycle.shutdown(reason="First call")
        self.assertEqual(self.lifecycle.state_machine.current_state, BuddyState.SHUTTING_DOWN)

        # Second call must be clean no-op
        await self.lifecycle.shutdown(reason="Second call")
        self.assertEqual(self.lifecycle.state_machine.current_state, BuddyState.SHUTTING_DOWN)

    async def test_handle_error_emits_event_and_updates_state(self) -> None:
        """Verify handle_error emits ErrorEvent and transitions to ERROR state."""
        await self.lifecycle.initialize()
        await self.lifecycle.start()
        self.assertEqual(self.lifecycle.state_machine.current_state, BuddyState.IDLE)

        # Transition to LISTENING first (since IDLE -> ERROR is not in transition table, but LISTENING -> ERROR is)
        self.lifecycle.state_machine.transition_to(BuddyState.LISTENING, reason="User spoke")

        errors_caught: list[ErrorEvent] = []

        def on_error(ev: ErrorEvent):
            errors_caught.append(ev)

        self.lifecycle.event_bus.subscribe(ErrorEvent, on_error)

        test_exception = RuntimeError("Mic hardware disconnected")
        await self.lifecycle.handle_error(test_exception, fatal=False, reason="Audio error")

        self.assertEqual(self.lifecycle.state_machine.current_state, BuddyState.ERROR)
        self.assertEqual(len(errors_caught), 1)
        self.assertEqual(errors_caught[0].error_type, "RuntimeError")
        self.assertIn("Mic hardware disconnected", errors_caught[0].message)


if __name__ == "__main__":
    unittest.main()
