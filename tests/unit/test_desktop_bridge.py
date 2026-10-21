"""Unit tests for Desktop Event Bridge and State Mapping."""

import asyncio
import unittest

from app.core import BuddyState, EventBus, StateChangedEvent
from app.core.events import ApplicationStartedEvent, ApplicationStoppingEvent, ErrorEvent
from app.desktop.bridge import RuntimeEventBridge, UiUpdate, VisualState
from app.tools.events import ToolExecutionCompletedEvent, ToolExecutionStartedEvent
from app.voice.events import (
    SpeechStartedEvent,
    SpeechStoppedEvent,
    VoiceCommandReceivedEvent,
    VoiceListeningStartedEvent,
    VoiceListeningStoppedEvent,
)


class TestDesktopEventBridge(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.event_bus = EventBus()
        self.updates: list[UiUpdate] = []
        self.bridge = RuntimeEventBridge(self.event_bus, on_update=self.updates.append)

    async def asyncTearDown(self) -> None:
        await self.event_bus.shutdown()

    async def test_state_mapping(self) -> None:
        # Starting state
        self.assertEqual(self.bridge.compute_visual_state(), VisualState.STARTING)

        # IDLE transition
        await self.event_bus.publish(
            StateChangedEvent(previous_state=BuddyState.STARTING, new_state=BuddyState.IDLE)
        )
        self.assertEqual(self.bridge.compute_visual_state(), VisualState.IDLE)
        self.assertEqual(self.updates[-1].visual_state, VisualState.IDLE)

        # LISTENING transition
        await self.event_bus.publish(
            StateChangedEvent(previous_state=BuddyState.IDLE, new_state=BuddyState.LISTENING)
        )
        self.assertEqual(self.bridge.compute_visual_state(), VisualState.LISTENING)

        # THINKING transition
        await self.event_bus.publish(
            StateChangedEvent(previous_state=BuddyState.LISTENING, new_state=BuddyState.THINKING)
        )
        self.assertEqual(self.bridge.compute_visual_state(), VisualState.THINKING)

        # EXECUTING transition
        await self.event_bus.publish(
            StateChangedEvent(previous_state=BuddyState.THINKING, new_state=BuddyState.EXECUTING)
        )
        self.assertEqual(self.bridge.compute_visual_state(), VisualState.EXECUTING)

        # SPEAKING transition
        await self.event_bus.publish(
            StateChangedEvent(previous_state=BuddyState.EXECUTING, new_state=BuddyState.SPEAKING)
        )
        self.assertEqual(self.bridge.compute_visual_state(), VisualState.SPEAKING)

        # ERROR transition
        await self.event_bus.publish(
            StateChangedEvent(previous_state=BuddyState.SPEAKING, new_state=BuddyState.ERROR)
        )
        self.assertEqual(self.bridge.compute_visual_state(), VisualState.ERROR)

        # SHUTTING_DOWN transition
        await self.event_bus.publish(
            StateChangedEvent(previous_state=BuddyState.ERROR, new_state=BuddyState.SHUTTING_DOWN)
        )
        self.assertEqual(self.bridge.compute_visual_state(), VisualState.SHUTTING_DOWN)

    async def test_paused_visual_state(self) -> None:
        await self.event_bus.publish(
            StateChangedEvent(previous_state=BuddyState.STARTING, new_state=BuddyState.IDLE)
        )
        self.assertEqual(self.bridge.compute_visual_state(), VisualState.IDLE)

        # Pause mic
        self.bridge.set_mic_paused(True)
        self.assertEqual(self.bridge.compute_visual_state(), VisualState.PAUSED)
        self.assertTrue(self.updates[-1].mic_paused)
        self.assertIn("paused", self.updates[-1].status_text.lower())

        # Resume mic
        self.bridge.set_mic_paused(False)
        self.assertEqual(self.bridge.compute_visual_state(), VisualState.IDLE)
        self.assertFalse(self.updates[-1].mic_paused)

    async def test_tool_events(self) -> None:
        await self.event_bus.publish(
            ToolExecutionStartedEvent(request_id="t1", tool_name="system.get_battery")
        )
        self.assertIn("system.get_battery", self.updates[-1].action_status)

        await self.event_bus.publish(
            ToolExecutionCompletedEvent(request_id="t1", tool_name="system.get_battery")
        )
        self.assertIn("Verified", self.updates[-1].action_status)

    async def test_conversation_and_speech_events(self) -> None:
        await self.event_bus.publish(VoiceCommandReceivedEvent(transcript="open notepad"))
        self.assertEqual(self.updates[-1].last_transcript, "open notepad")

        await self.event_bus.publish(SpeechStartedEvent(text="Opening Notepad."))
        self.assertEqual(self.updates[-1].last_response, "Opening Notepad.")
