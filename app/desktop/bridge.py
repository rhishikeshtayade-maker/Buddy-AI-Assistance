"""BUDDY Desktop Event Bridge.

Maps core runtime states, voice pipeline events, and tool executor events into
strongly typed, thread-safe UI updates for the animated Glass HUD.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from app.core import BuddyState, StateChangedEvent
from app.core.events import ApplicationStartedEvent, ApplicationStoppingEvent, ErrorEvent, EventBus
from app.tools.events import (
    ToolConfirmationRequiredEvent,
    ToolDeniedEvent,
    ToolExecutionCompletedEvent,
    ToolExecutionFailedEvent,
    ToolExecutionStartedEvent,
)
from app.voice.events import (
    SpeechStartedEvent,
    SpeechStoppedEvent,
    VoiceCommandReceivedEvent,
    VoiceListeningStartedEvent,
    VoiceListeningStoppedEvent,
    VoicePartialTranscriptEvent,
    VoiceSpeechDetectedEvent,
    WakeWordDetectedEvent,
)

logger = logging.getLogger("buddy.desktop.bridge")


class VisualState(str, Enum):
    """High-level visual states driving HUD animations and color palettes."""

    STARTING = "STARTING"
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    EXECUTING = "EXECUTING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"
    SHUTTING_DOWN = "SHUTTING_DOWN"
    PAUSED = "PAUSED"


@dataclass(frozen=True)
class UiUpdate:
    """Immutable snapshot delivered to the GUI thread for rendering."""

    visual_state: VisualState
    core_state: BuddyState
    status_text: str
    mic_active: bool = False
    mic_paused: bool = False
    audio_level: float = 0.0
    action_status: Optional[str] = None
    last_transcript: Optional[str] = None
    last_response: Optional[str] = None
    error_message: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class RuntimeEventBridge:
    """Bridges asyncio EventBus events to synchronous GUI update callbacks."""

    def __init__(
        self,
        event_bus: EventBus,
        on_update: Optional[Callable[[UiUpdate], Any]] = None,
    ) -> None:
        self._event_bus = event_bus
        self._on_update = on_update

        # Internal tracked state
        self._core_state: BuddyState = BuddyState.STARTING
        self._mic_paused: bool = False
        self._mic_active: bool = False
        self._audio_level: float = 0.0
        self._status_text: str = "Starting BUDDY..."
        self._action_status: Optional[str] = None
        self._last_transcript: Optional[str] = None
        self._last_response: Optional[str] = None
        self._error_message: Optional[str] = None

        self._subscribe_events()

    def set_update_callback(self, callback: Callable[[UiUpdate], Any]) -> None:
        self._on_update = callback

    def set_mic_paused(self, paused: bool) -> None:
        """Update listening pause flag and push UI update."""
        self._mic_paused = paused
        if paused:
            self._status_text = "Listening paused"
            self._mic_active = False
        else:
            if self._core_state == BuddyState.IDLE:
                self._status_text = "Ready — listening for 'Hey BUDDY'"
        self.emit_update()

    def set_audio_level(self, level: float) -> None:
        """Update reactive audio energy level."""
        self._audio_level = max(0.0, min(1.0, level))

    def compute_visual_state(self) -> VisualState:
        """Derive the authoritative visual state from core state and flags."""
        if self._core_state == BuddyState.SHUTTING_DOWN:
            return VisualState.SHUTTING_DOWN
        if self._core_state == BuddyState.STARTING:
            return VisualState.STARTING
        if self._core_state == BuddyState.ERROR:
            return VisualState.ERROR
        if self._mic_paused:
            return VisualState.PAUSED
        if self._core_state == BuddyState.LISTENING:
            return VisualState.LISTENING
        if self._core_state == BuddyState.THINKING:
            return VisualState.THINKING
        if self._core_state == BuddyState.EXECUTING:
            return VisualState.EXECUTING
        if self._core_state == BuddyState.SPEAKING:
            return VisualState.SPEAKING
        return VisualState.IDLE

    def build_snapshot(self) -> UiUpdate:
        visual = self.compute_visual_state()
        return UiUpdate(
            visual_state=visual,
            core_state=self._core_state,
            status_text=self._status_text,
            mic_active=self._mic_active and not self._mic_paused,
            mic_paused=self._mic_paused,
            audio_level=self._audio_level,
            action_status=self._action_status,
            last_transcript=self._last_transcript,
            last_response=self._last_response,
            error_message=self._error_message,
        )

    def emit_update(self) -> None:
        """Push current snapshot to the GUI callback."""
        if self._on_update is None:
            return
        snapshot = self.build_snapshot()
        try:
            self._on_update(snapshot)
        except Exception as e:
            logger.warning("Error in UI update callback: %s", e)

    def set_action_status(self, text: Optional[str]) -> None:
        self._action_status = text
        if text:
            self._status_text = text
        self.emit_update()

    def set_conversation_turn(self, transcript: Optional[str], response: Optional[str]) -> None:
        if transcript:
            self._last_transcript = transcript
        if response:
            self._last_response = response
        self.emit_update()

    # -------------------------------------------------------------------------
    # Event Handlers
    # -------------------------------------------------------------------------

    def _subscribe_events(self) -> None:
        self._event_bus.subscribe(StateChangedEvent, self._handle_state_changed)
        self._event_bus.subscribe(ApplicationStartedEvent, self._handle_app_started)
        self._event_bus.subscribe(ApplicationStoppingEvent, self._handle_app_stopping)
        self._event_bus.subscribe(ErrorEvent, self._handle_error_event)

        # Voice events
        self._event_bus.subscribe(VoiceListeningStartedEvent, self._handle_listening_started)
        self._event_bus.subscribe(VoiceListeningStoppedEvent, self._handle_listening_stopped)
        self._event_bus.subscribe(WakeWordDetectedEvent, self._handle_wake_word_detected)
        self._event_bus.subscribe(VoiceCommandReceivedEvent, self._handle_command_received)
        self._event_bus.subscribe(VoicePartialTranscriptEvent, self._handle_partial_transcript)
        self._event_bus.subscribe(SpeechStartedEvent, self._handle_speech_started)
        self._event_bus.subscribe(SpeechStoppedEvent, self._handle_speech_stopped)

        # Tool events
        self._event_bus.subscribe(ToolExecutionStartedEvent, self._handle_tool_started)
        self._event_bus.subscribe(ToolExecutionCompletedEvent, self._handle_tool_completed)
        self._event_bus.subscribe(ToolExecutionFailedEvent, self._handle_tool_failed)
        self._event_bus.subscribe(ToolConfirmationRequiredEvent, self._handle_tool_confirm)
        self._event_bus.subscribe(ToolDeniedEvent, self._handle_tool_denied)

    async def _handle_state_changed(self, event: StateChangedEvent) -> None:
        self._core_state = event.new_state
        if event.new_state == BuddyState.IDLE:
            self._status_text = "Listening paused" if self._mic_paused else "Ready — listening for 'Hey BUDDY'"
            self._action_status = None
        elif event.new_state == BuddyState.LISTENING:
            self._status_text = "Listening..."
        elif event.new_state == BuddyState.THINKING:
            self._status_text = "Thinking..."
        elif event.new_state == BuddyState.EXECUTING:
            if not self._action_status:
                self._status_text = "Executing action..."
        elif event.new_state == BuddyState.SPEAKING:
            self._status_text = "BUDDY speaking..."
        elif event.new_state == BuddyState.ERROR:
            self._status_text = "Error encountered"
        elif event.new_state == BuddyState.SHUTTING_DOWN:
            self._status_text = "Shutting down BUDDY..."
        self.emit_update()

    async def _handle_app_started(self, event: ApplicationStartedEvent) -> None:
        self._core_state = BuddyState.IDLE
        self._status_text = "Ready — listening for 'Hey BUDDY'"
        self.emit_update()

    async def _handle_app_stopping(self, event: ApplicationStoppingEvent) -> None:
        self._core_state = BuddyState.SHUTTING_DOWN
        self._status_text = "Shutting down BUDDY..."
        self.emit_update()

    async def _handle_error_event(self, event: ErrorEvent) -> None:
        self._error_message = event.message
        self._status_text = f"Notice: {event.message}"
        self.emit_update()

    async def _handle_listening_started(self, event: VoiceListeningStartedEvent) -> None:
        self._mic_active = True
        self.emit_update()

    async def _handle_listening_stopped(self, event: VoiceListeningStoppedEvent) -> None:
        self._mic_active = False
        self.emit_update()

    async def _handle_wake_word_detected(self, event: WakeWordDetectedEvent) -> None:
        self._status_text = "Wake word detected!"
        self.emit_update()

    async def _handle_command_received(self, event: VoiceCommandReceivedEvent) -> None:
        if event.transcript:
            self._last_transcript = event.transcript
            self._status_text = f"Heard: \"{event.transcript}\""
        self.emit_update()

    async def _handle_partial_transcript(self, event: VoicePartialTranscriptEvent) -> None:
        if event.partial_text:
            self._status_text = f"Heard: \"{event.partial_text}\"…"
            self.emit_update()

    async def _handle_speech_started(self, event: SpeechStartedEvent) -> None:
        if event.text and event.text != "[stream]":
            self._last_response = event.text
        self._status_text = "BUDDY speaking..."
        self.emit_update()

    async def _handle_speech_stopped(self, event: SpeechStoppedEvent) -> None:
        if self._core_state == BuddyState.IDLE:
            self._status_text = "Ready — listening for 'Hey BUDDY'"
        self.emit_update()

    async def _handle_tool_started(self, event: ToolExecutionStartedEvent) -> None:
        self._action_status = f"Executing {event.tool_name}…"
        self._status_text = self._action_status
        self.emit_update()

    async def _handle_tool_completed(self, event: ToolExecutionCompletedEvent) -> None:
        self._action_status = f"Verified: {event.tool_name}"
        self._status_text = self._action_status
        self.emit_update()

    async def _handle_tool_failed(self, event: ToolExecutionFailedEvent) -> None:
        self._action_status = f"Failed: {event.tool_name}"
        self._status_text = self._action_status
        self.emit_update()

    async def _handle_tool_confirm(self, event: ToolConfirmationRequiredEvent) -> None:
        self._action_status = f"Confirmation required: {event.tool_name}"
        self._status_text = self._action_status
        self.emit_update()

    async def _handle_tool_denied(self, event: ToolDeniedEvent) -> None:
        self._action_status = f"Denied: {event.tool_name}"
        self._status_text = self._action_status
        self.emit_update()
