"""End-to-End Voice + AI + TTS Pipeline Integration Tests."""

import asyncio
import unittest
from app.ai import (
    AIRouter,
    ConversationManager,
    MockAIProvider,
)
from app.core import (
    BuddyConfig,
    BuddyState,
    EventBus,
    StateMachine,
)
from app.voice import (
    MockAudioCapture,
    MockSTTProvider,
    MockTTSProvider,
    MockVAD,
    SpeechStartedEvent,
    SpeechStoppedEvent,
    VADState,
    VoiceCommandReceivedEvent,
    VoicePipeline,
)


class TestVoiceAIIntegration(unittest.IsolatedAsyncioTestCase):
    """Full deterministic integration test verifying Voice -> Conversation -> AI -> TTS cycle."""

    async def asyncSetUp(self) -> None:
        self.config = BuddyConfig(
            app_env="testing",
            ai_provider="mock",
            voice_timeout=2.0,
        )
        self.event_bus = EventBus()
        self.state_machine = StateMachine(BuddyState.IDLE)

        # Connect state machine transitions to event bus
        self.state_machine.set_transition_callback(
            lambda prev, new, reason, ts: self.event_bus.publish_sync(
                __import__("app.core").core.StateChangedEvent(
                    previous_state=prev, new_state=new, reason=reason, timestamp=ts
                )
            )
        )

        # Mock Voice Components
        self.mock_capture = MockAudioCapture()
        self.mock_vad = MockVAD([VADState.WAITING, VADState.SPEAKING, VADState.SILENCE, VADState.COMPLETED])
        self.mock_stt = MockSTTProvider(default_transcript="Hello BUDDY")
        self.mock_tts = MockTTSProvider()

        self.voice_pipeline = VoicePipeline(
            config=self.config,
            event_bus=self.event_bus,
            state_machine=self.state_machine,
            capture=self.mock_capture,
            vad=self.mock_vad,
            stt=self.mock_stt,
            tts=self.mock_tts,
        )

        # Mock AI Components
        self.mock_ai = MockAIProvider(default_response="Hello! I am BUDDY, ready to help.")
        self.router = AIRouter(self.config)
        self.router.register_provider("mock", self.mock_ai)

        # Conversation Manager
        self.conv_mgr = ConversationManager(
            config=self.config,
            event_bus=self.event_bus,
            state_machine=self.state_machine,
            router=self.router,
            voice_pipeline=self.voice_pipeline,
        )

    async def asyncTearDown(self) -> None:
        await self.event_bus.shutdown()

    async def test_mock_end_to_end_voice_ai_tts_cycle(self) -> None:
        """Section 23: Complete Mock End-to-End Pipeline test.

        Flow:
        Mock Microphone -> Mock VAD -> Mock STT ("Hello BUDDY") ->
        VoiceCommandReceivedEvent -> ConversationManager -> Mock AI ("Hello! I am BUDDY, ready to help.") ->
        Mock TTS -> Speaker -> IDLE
        """
        all_events = []

        async def capture_event(ev):
            all_events.append(ev)

        self.event_bus.subscribe(None, capture_event)

        # 1. State must start at IDLE
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

        # 2. Voice capture executes:
        # IDLE -> LISTENING -> (VAD) -> THINKING -> STT Result ->
        # VoiceCommandReceivedEvent automatically triggers ConversationManager ->
        # THINKING -> Mock AI -> SPEAKING -> Mock TTS -> IDLE
        stt_result = await self.voice_pipeline.listen_for_command(timeout=2.0)
        self.assertIsNotNone(stt_result)
        self.assertEqual(stt_result.transcript, "Hello BUDDY")

        # 3. Verify AI Response content and TTS invocation occurred automatically
        self.assertEqual(len(self.conv_mgr.history), 2)
        self.assertEqual(self.conv_mgr.history[0].content, "Hello BUDDY")
        self.assertEqual(self.conv_mgr.history[1].content, "Hello! I am BUDDY, ready to help.")
        self.assertIn("Hello! I am BUDDY, ready to help.", self.mock_tts.spoken_phrases)

        # 4. Verify State Machine ended back in IDLE
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

        # 5. Verify Full Event Chain Emitted
        event_types = [type(e) for e in all_events]
        self.assertIn(VoiceCommandReceivedEvent, event_types)
        self.assertIn(SpeechStartedEvent, event_types)
        self.assertIn(SpeechStoppedEvent, event_types)

        # 7. Check full state transition sequence
        state_history = [rec.new_state for rec in self.state_machine.history]
        self.assertIn(BuddyState.LISTENING, state_history)
        self.assertIn(BuddyState.THINKING, state_history)
        self.assertIn(BuddyState.SPEAKING, state_history)
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)


if __name__ == "__main__":
    unittest.main()
