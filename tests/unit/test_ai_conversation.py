"""Unit tests for BUDDY Conversation Manager."""

import asyncio
import unittest
from app.ai import (
    AIProviderError,
    AIRequestStartedEvent,
    AIResponseReceivedEvent,
    AIRouter,
    ChatMessage,
    ConversationEndedEvent,
    ConversationErrorEvent,
    ConversationManager,
    ConversationStartedEvent,
    MessageRole,
    MockAIProvider,
    UserMessageReceivedEvent,
)
from app.core import (
    BuddyConfig,
    BuddyState,
    EventBus,
    StateMachine,
)


class TestConversationManager(unittest.IsolatedAsyncioTestCase):
    """Test suite verifying conversation turn execution, history bounding, and events."""

    async def asyncSetUp(self) -> None:
        self.config = BuddyConfig(
            app_env="testing",
            ai_provider="mock",
            conversation_max_messages=4,
        )
        self.event_bus = EventBus()
        self.state_machine = StateMachine(BuddyState.IDLE)
        self.mock_ai = MockAIProvider(default_response="Mock reply.")

        self.router = AIRouter(self.config)
        self.router.register_provider("mock", self.mock_ai)

        self.conv_mgr = ConversationManager(
            config=self.config,
            event_bus=self.event_bus,
            state_machine=self.state_machine,
            router=self.router,
        )

    async def asyncTearDown(self) -> None:
        await self.event_bus.shutdown()

    async def test_process_user_turn_and_events(self) -> None:
        """Verify normal user turn appends user and assistant messages, emitting events."""
        events_emitted = []

        async def capture_event(ev):
            events_emitted.append(ev)

        self.event_bus.subscribe(None, capture_event)

        response = await self.conv_mgr.process_user_turn("Hello BUDDY")

        self.assertEqual(response.content, "Mock reply.")
        self.assertEqual(len(self.conv_mgr.history), 2)
        self.assertEqual(self.conv_mgr.history[0].role, MessageRole.USER)
        self.assertEqual(self.conv_mgr.history[0].content, "Hello BUDDY")
        self.assertEqual(self.conv_mgr.history[1].role, MessageRole.ASSISTANT)
        self.assertEqual(self.conv_mgr.history[1].content, "Mock reply.")

        # Verify events
        event_types = [type(e) for e in events_emitted]
        self.assertIn(ConversationStartedEvent, event_types)
        self.assertIn(UserMessageReceivedEvent, event_types)
        self.assertIn(AIRequestStartedEvent, event_types)
        self.assertIn(AIResponseReceivedEvent, event_types)

    async def test_context_limit_truncation(self) -> None:
        """Verify oldest messages are pruned when exceeding conversation_max_messages."""
        # Max messages configured to 4 (2 turns)
        await self.conv_mgr.process_user_turn("Turn 1")
        await self.conv_mgr.process_user_turn("Turn 2")
        self.assertEqual(len(self.conv_mgr.history), 4)

        # Turn 3 adds 2 messages, history should truncate oldest 2 messages
        await self.conv_mgr.process_user_turn("Turn 3")
        self.assertEqual(len(self.conv_mgr.history), 4)
        self.assertEqual(self.conv_mgr.history[-2].content, "Turn 3")

    async def test_clear_history(self) -> None:
        """Verify clear_history flushes memory and emits ConversationEndedEvent."""
        events = []
        self.event_bus.subscribe(ConversationEndedEvent, lambda e: events.append(e))

        await self.conv_mgr.process_user_turn("Test input")
        self.assertEqual(len(self.conv_mgr.history), 2)

        await self.conv_mgr.clear_history()
        self.assertEqual(len(self.conv_mgr.history), 0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].total_turns, 2)

    async def test_turn_failure_recovery_and_events(self) -> None:
        """Verify provider failure emits ConversationErrorEvent and recovers state."""
        self.mock_ai.simulate_failure = True
        events = []
        self.event_bus.subscribe(ConversationErrorEvent, lambda e: events.append(e))

        with self.assertRaises(AIProviderError):
            await self.conv_mgr.process_user_turn("Will fail")

        self.assertEqual(len(events), 1)
        self.assertIn("AIProviderError", events[0].error_type)
        # State machine recovered to IDLE
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)


if __name__ == "__main__":
    unittest.main()
