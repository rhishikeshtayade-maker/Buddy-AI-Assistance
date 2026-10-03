"""Unit & Integration tests for BUDDY Voice Pipeline Orchestrator."""

import asyncio
import unittest
from app.core import (
    BuddyConfig,
    BuddyState,
    EventBus,
    StateMachine,
)
from app.voice import (
    AudioData,
    MockAudioCapture,
    MockSTTProvider,
    MockTTSProvider,
    MockVAD,
    SpeechStartedEvent,
    SpeechStoppedEvent,
    VADState,
    VoiceCommandReceivedEvent,
    VoiceListeningStartedEvent,
    VoiceListeningStoppedEvent,
    VoicePipeline,
    VoiceRecognitionFailedEvent,
)


class TestVoicePipelineIntegration(unittest.IsolatedAsyncioTestCase):
    """End-to-end integration test of the Voice Pipeline without live audio hardware."""

    async def asyncSetUp(self) -> None:
        self.config = BuddyConfig(app_env="testing", voice_timeout=2.0)
        self.event_bus = EventBus()
        self.state_machine = StateMachine(BuddyState.IDLE)

        # Wire state machine to event bus
        self.state_machine.set_transition_callback(
            lambda prev, new, reason, ts: self.event_bus.publish_sync(
                # Import here to avoid circular imports
                __import__("app.core").core.StateChangedEvent(
                    previous_state=prev, new_state=new, reason=reason, timestamp=ts
                )
            )
        )

        self.mock_capture = MockAudioCapture()
        self.mock_vad = MockVAD([VADState.WAITING, VADState.SPEAKING, VADState.SILENCE, VADState.COMPLETED])
        self.mock_stt = MockSTTProvider(default_transcript="Hello BUDDY", confidence=0.99)
        self.mock_tts = MockTTSProvider()

        self.pipeline = VoicePipeline(
            config=self.config,
            event_bus=self.event_bus,
            state_machine=self.state_machine,
            capture=self.mock_capture,
            vad=self.mock_vad,
            stt=self.mock_stt,
            tts=self.mock_tts,
        )

    async def asyncTearDown(self) -> None:
        await self.event_bus.shutdown()

    async def test_deterministic_voice_command_flow(self) -> None:
        """Section 23: Complete mock-based integration test:

        Mock microphone -> Mock VAD -> Mock STT -> "Hello BUDDY" -> VoiceCommandReceivedEvent.
        Verifies:
        - State transitions: IDLE -> LISTENING -> THINKING
        - Events: VoiceListeningStartedEvent -> VoiceListeningStoppedEvent -> VoiceCommandReceivedEvent
        - Transcript: "Hello BUDDY"
        - Cleanup: Capture is stopped
        """
        captured_events = []

        async def record_event(ev):
            captured_events.append(ev)

        self.event_bus.subscribe(None, record_event)

        # 1. State must start in IDLE
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

        # 2. Execute listening flow
        result = await self.pipeline.listen_for_command(timeout=2.0)

        # 3. Verify STT result
        self.assertIsNotNone(result)
        self.assertEqual(result.transcript, "Hello BUDDY")
        self.assertEqual(result.confidence, 0.99)

        # 4. Verify State Machine reached THINKING
        self.assertEqual(self.state_machine.current_state, BuddyState.THINKING)

        # 5. Verify Event Sequencing
        event_types = [type(e) for e in captured_events]
        self.assertIn(VoiceListeningStartedEvent, event_types)
        self.assertIn(VoiceListeningStoppedEvent, event_types)
        self.assertIn(VoiceCommandReceivedEvent, event_types)

        # Inspect VoiceCommandReceivedEvent content
        cmd_event = next(e for e in captured_events if isinstance(e, VoiceCommandReceivedEvent))
        self.assertEqual(cmd_event.transcript, "Hello BUDDY")
        self.assertEqual(cmd_event.provider, "mock")

        # 6. Verify Hardware Cleanup
        self.assertFalse(self.mock_capture.is_capturing)

    async def test_voice_recognition_failure_and_state_recovery(self) -> None:
        """Verify STT failure emits VoiceRecognitionFailedEvent and recovers state to IDLE."""
        self.mock_stt.simulate_failure = True
        captured_events = []

        self.event_bus.subscribe(VoiceRecognitionFailedEvent, lambda e: captured_events.append(e))

        result = await self.pipeline.listen_for_command(timeout=2.0)

        self.assertIsNone(result)
        self.assertEqual(len(captured_events), 1)
        self.assertEqual(captured_events[0].error_type, "STTError")

        # Must recover cleanly to IDLE
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)
        self.assertFalse(self.mock_capture.is_capturing)

    async def test_listening_cancellation(self) -> None:
        """Verify cancel_listening() aborts capture and returns to IDLE."""
        # Setup VAD that stays WAITING so we can cancel it
        self.mock_vad = MockVAD([VADState.WAITING] * 100)
        self.pipeline._vad = self.mock_vad

        async def run_listen():
            return await self.pipeline.listen_for_command(timeout=5.0)

        listen_task = asyncio.create_task(run_listen())
        await asyncio.sleep(0.05)

        # Pipeline should be in LISTENING state
        self.assertEqual(self.state_machine.current_state, BuddyState.LISTENING)

        # Cancel listening
        self.pipeline.cancel_listening()
        res = await listen_task

        self.assertIsNone(res)
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)
        self.assertFalse(self.mock_capture.is_capturing)

    async def test_speak_and_speech_events(self) -> None:
        """Verify speak() triggers SpeechStartedEvent and SpeechStoppedEvent."""
        captured_events = []

        self.event_bus.subscribe(None, lambda e: captured_events.append(e))

        await self.pipeline.speak("BUDDY is standing by.")

        event_types = [type(e) for e in captured_events]
        self.assertIn(SpeechStartedEvent, event_types)
        self.assertIn(SpeechStoppedEvent, event_types)
        self.assertIn("BUDDY is standing by.", self.mock_tts.spoken_phrases)


if __name__ == "__main__":
    unittest.main()
