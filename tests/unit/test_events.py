"""Unit tests for BUDDY Async Event Bus and Core Event Definitions."""

import asyncio
import unittest
from app.core import (
    ApplicationStartedEvent,
    ApplicationStoppedEvent,
    ApplicationStoppingEvent,
    BaseEvent,
    BuddyState,
    ErrorEvent,
    EventBus,
    HealthChangedEvent,
    StateChangedEvent,
)


class TestEventBus(unittest.IsolatedAsyncioTestCase):
    """Test suite verifying async event bus dispatch, isolation, and subscription lifecycle."""

    async def asyncSetUp(self) -> None:
        self.bus = EventBus()

    async def asyncTearDown(self) -> None:
        await self.bus.shutdown()

    async def test_subscribe_and_publish_async_handler(self) -> None:
        """Verify an async handler receives a typed event."""
        received: list[StateChangedEvent] = []

        async def handler(event: StateChangedEvent) -> None:
            received.append(event)

        self.bus.subscribe(StateChangedEvent, handler)

        event = StateChangedEvent(
            previous_state=BuddyState.STARTING,
            new_state=BuddyState.IDLE,
            reason="Init complete",
        )
        await self.bus.publish(event)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].previous_state, BuddyState.STARTING)
        self.assertEqual(received[0].new_state, BuddyState.IDLE)
        self.assertEqual(received[0].reason, "Init complete")

    async def test_multiple_subscribers_deterministic_order(self) -> None:
        """Verify multiple subscribers are executed in order."""
        call_order: list[int] = []

        async def h1(event: ApplicationStartedEvent) -> None:
            call_order.append(1)

        async def h2(event: ApplicationStartedEvent) -> None:
            call_order.append(2)

        self.bus.subscribe(ApplicationStartedEvent, h1)
        self.bus.subscribe(ApplicationStartedEvent, h2)

        await self.bus.publish(ApplicationStartedEvent(app_name="BUDDY"))
        self.assertEqual(call_order, [1, 2])

    async def test_unsubscribe(self) -> None:
        """Verify handler unsubscribes cleanly and receives no subsequent events."""
        received: list[BaseEvent] = []

        def handler(event: ErrorEvent) -> None:
            received.append(event)

        self.bus.subscribe(ErrorEvent, handler)
        await self.bus.publish(ErrorEvent(message="Error 1"))
        self.assertEqual(len(received), 1)

        removed = self.bus.unsubscribe(ErrorEvent, handler)
        self.assertTrue(removed)

        await self.bus.publish(ErrorEvent(message="Error 2"))
        self.assertEqual(len(received), 1)

    async def test_handler_failure_isolation(self) -> None:
        """Verify that a failing handler does not crash the bus or halt other subscribers."""
        successful_calls: list[str] = []

        def faulty_handler(event: BaseEvent) -> None:
            raise RuntimeError("Subscriber explosion!")

        def healthy_handler(event: BaseEvent) -> None:
            successful_calls.append("healthy")

        self.bus.subscribe(HealthChangedEvent, faulty_handler)
        self.bus.subscribe(HealthChangedEvent, healthy_handler)

        event = HealthChangedEvent(
            previous_status="HEALTHY",
            new_status="DEGRADED",
            message="Degraded warning",
        )
        # Must NOT raise exception despite faulty_handler crashing
        await self.bus.publish(event)

        self.assertEqual(successful_calls, ["healthy"])

    async def test_global_subscriber(self) -> None:
        """Verify None event_type subscribes to all events."""
        all_events: list[BaseEvent] = []

        def catch_all(event: BaseEvent) -> None:
            all_events.append(event)

        self.bus.subscribe(None, catch_all)

        await self.bus.publish(ApplicationStartedEvent())
        await self.bus.publish(ApplicationStoppingEvent())
        await self.bus.publish(ApplicationStoppedEvent())

        self.assertEqual(len(all_events), 3)

    async def test_shutdown_clears_and_ignores(self) -> None:
        """Verify shutting down event bus ignores subsequent publications."""
        received: list[BaseEvent] = []

        self.bus.subscribe(ApplicationStartedEvent, lambda e: received.append(e))
        await self.bus.shutdown()
        self.assertFalse(self.bus.is_active)

        await self.bus.publish(ApplicationStartedEvent())
        self.assertEqual(len(received), 0)


if __name__ == "__main__":
    unittest.main()
