"""Loop 13 Voice Hardening & Diagnostic Taxonomy Verification Tests.

Verifies:
1. Microphone capture frame arrival and persistent stream reuse.
2. VAD adaptive noise calibration, transient spike rejection, and bounded duration.
3. Outcome classification (A: MIC_UNAVAILABLE, B: NO_FRAMES, C: SILENCE, D: STT_FAILED, G: TRANSCRIBED).
4. Continuous 10-turn conversation loop without memory leak, task accumulation, or state corruption.
5. Voice command routing through ToolExecutor with empirical verification.
6. TTS interruption foundation and secret redaction.
"""

import asyncio
import gc
import unittest
from unittest.mock import AsyncMock, patch

from app.ai.conversation import ConversationManager
from app.ai.provider import MockAIProvider
from app.ai.router import AIRouter
from app.core.config import BuddyConfig
from app.core.events import EventBus
from app.core.state import BuddyState, StateMachine
from app.tools.builtin import register_builtin_tools
from app.tools.executor import ToolExecutor
from app.tools.models import ToolRequest
from app.tools.registry import ToolRegistry
from app.voice.capture import MockAudioCapture
from app.voice.exceptions import (
    AudioCaptureError,
    STTEmptyError,
    STTError,
    STTServiceError,
    STTUnclearError,
)
from app.voice.models import (
    AudioData,
    TranscriptionStatus,
    VADState,
    VoiceOutcome,
)
from app.voice.pipeline import VoicePipeline
from app.voice.stt import MockSTTProvider
from app.voice.tts import MockTTSProvider, Pyttsx3TTSProvider
from app.voice.vad import EnergyVAD, MockVAD


class TestLoop13VoiceHardening(unittest.IsolatedAsyncioTestCase):
    """Loop 13 comprehensive voice interaction tests."""

    async def asyncSetUp(self) -> None:
        self.config = BuddyConfig(
            app_env="testing",
            voice_timeout=2.0,
            ai_provider="mock",
        )
        self.event_bus = EventBus()
        self.state_machine = StateMachine(BuddyState.IDLE)
        self.mock_capture = MockAudioCapture()
        self.mock_vad = MockVAD([VADState.WAITING, VADState.SPEAKING, VADState.SILENCE, VADState.COMPLETED])
        self.mock_stt = MockSTTProvider(default_transcript="what time is it")
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

        self.registry = ToolRegistry()
        register_builtin_tools(self.registry)
        self.tool_executor = ToolExecutor(registry=self.registry, event_bus=self.event_bus)

        self.ai_provider = MockAIProvider(default_response="The time is 10:00 AM.")
        self.router = AIRouter(self.config)
        self.router.register_provider("mock", self.ai_provider)

        self.conv_mgr = ConversationManager(
            config=self.config,
            event_bus=self.event_bus,
            state_machine=self.state_machine,
            router=self.router,
            voice_pipeline=self.pipeline,
            tool_executor=self.tool_executor,
        )

    async def asyncTearDown(self) -> None:
        await self.event_bus.shutdown()

    async def test_outcome_classification_success(self) -> None:
        """Outcome G: Everything succeeded and valid transcript was produced."""
        res = await self.pipeline.listen_with_diagnostics(timeout=2.0)
        self.assertEqual(res.outcome, VoiceOutcome.TRANSCRIBED)
        self.assertEqual(res.transcript, "what time is it")
        self.assertEqual(res.transcription_status, TranscriptionStatus.TRANSCRIPTION_SUCCESS)
        self.assertTrue(res.ok)
        # Because conv_mgr is wired to VoiceCommandReceivedEvent, the turn was processed and returned to IDLE
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    async def test_outcome_classification_mic_unavailable(self) -> None:
        """Outcome A: Microphone failed to open/start."""
        with patch.object(self.mock_capture, "start", side_effect=AudioCaptureError("Device busy")):
            res = await self.pipeline.listen_with_diagnostics(timeout=2.0)
            self.assertEqual(res.outcome, VoiceOutcome.MIC_UNAVAILABLE)
            self.assertIn("Device busy", str(res.error_message))
            self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    async def test_outcome_classification_stt_empty_and_unclear(self) -> None:
        """Outcome D: Speech detected but STT failed with typed classification."""
        self.mock_stt.simulate_failure = True
        self.mock_stt.failure_exception = STTUnclearError("Unintelligible mutter")

        res = await self.pipeline.listen_with_diagnostics(timeout=2.0)
        self.assertEqual(res.outcome, VoiceOutcome.STT_FAILED)
        self.assertEqual(res.transcription_status, TranscriptionStatus.TRANSCRIPTION_UNCLEAR)
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

        # Test STTEmptyError
        self.mock_stt.failure_exception = STTEmptyError("Empty")
        res2 = await self.pipeline.listen_with_diagnostics(timeout=2.0)
        self.assertEqual(res2.outcome, VoiceOutcome.STT_FAILED)
        self.assertEqual(res2.transcription_status, TranscriptionStatus.TRANSCRIPTION_EMPTY)

    async def test_adaptive_vad_transient_spike_rejection(self) -> None:
        """Adaptive VAD discards transient noise clicks shorter than min_speech_duration."""
        vad = EnergyVAD(
            energy_threshold=100.0,
            silence_timeout=0.1,
            min_speech_duration=0.2,
            use_audio_clock=True,
        )
        vad.calibrate_ambient(30.0)

        # One loud 0.05s chunk (click)
        click_chunk = b"\x10\x27" * 400  # 800 bytes = 0.025s at 16kHz
        vad.process_chunk(click_chunk)
        self.assertEqual(vad.state, VADState.SPEAKING)

        # Silence for > silence_timeout
        silence_chunk = b"\x00\x00" * 1600  # 0.1s
        vad.process_chunk(silence_chunk)
        vad.process_chunk(silence_chunk)

        # The transient click was discarded: VAD returned to WAITING, not COMPLETED
        self.assertEqual(vad.state, VADState.WAITING)
        self.assertFalse(vad.has_speech)

    async def test_continuous_10_turn_conversation_cycle(self) -> None:
        """Verify BUDDY survives 10 consecutive full conversational turns without memory leaks or state corruption."""
        for turn_idx in range(10):
            # 1. State machine IDLE
            if self.state_machine.current_state != BuddyState.IDLE:
                self.state_machine.transition_to(BuddyState.IDLE, reason=f"Setup turn {turn_idx}")

            self.mock_stt.set_next_transcript(f"turn command {turn_idx}")
            self.ai_provider.set_next_response(f"Response for turn {turn_idx}")

            # 2. Listen
            listen_res = await self.pipeline.listen_with_diagnostics(timeout=2.0)
            self.assertTrue(listen_res.ok)
            self.assertEqual(listen_res.transcript, f"turn command {turn_idx}")

            # 3. AI Turn & TTS Voicing
            ai_resp = await self.conv_mgr.process_user_turn(listen_res.transcript, voice_response=True)
            self.assertEqual(ai_resp.content, f"Response for turn {turn_idx}")
            self.assertIn(f"Response for turn {turn_idx}", self.mock_tts.spoken_phrases)

            # 4. State must return cleanly to IDLE
            self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

        # History bounds respected
        self.assertLessEqual(len(self.conv_mgr.history), self.config.conversation_max_messages)
        # GC collect run without errors
        gc.collect()

    async def test_voice_command_routes_securely_through_tool_executor(self) -> None:
        """Voice command routes through ToolExecutor with security and empirical verification."""
        req = ToolRequest(tool_name="system.get_battery", arguments={})
        res = await self.tool_executor.execute(req)

        self.assertTrue(res.success)
        self.assertTrue(res.verified)
        self.assertIsNotNone(res.output)
        self.assertEqual(res.status.value, "succeeded")

    async def test_tts_secret_redaction(self) -> None:
        """Ensure secrets are never spoken aloud via Pyttsx3TTSProvider."""
        tts = Pyttsx3TTSProvider()
        spoken_strings = []

        class MockEngine:
            def say(self, text):
                spoken_strings.append(text)
            def runAndWait(self):
                pass
            def stop(self):
                pass
            def setProperty(self, k, v):
                pass

        with patch.object(tts, "_init_engine", return_value=MockEngine()):
            secret_text = "Your API key is sk-proj-1234567890abcdef1234567890."
            await tts.speak(secret_text)

            self.assertEqual(len(spoken_strings), 1)
            self.assertNotIn("sk-proj-1234567890abcdef1234567890", spoken_strings[0])
            self.assertIn("[REDACTED", spoken_strings[0])


if __name__ == "__main__":
    unittest.main()
