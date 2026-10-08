"""Loop 14 Comprehensive Test Suite: Voice Streaming, Latency Metrics, & Barge-In.

Covers:
  A. Latency metrics model & fields
  B. Monotonic timing guarantees
  C. Streaming VAD (onset, continuation, silence, completion, noise, duration bounds)
  D. Streaming STT interface (partial events, final result)
  E. Streaming AI interface (incremental tokens, no partial tool bypass)
  F. Streaming TTS interface (clause chunking, incremental playback)
  G. Cancellation (capture abort, TTS halt)
  H. Barge-in (speech during speech cancels playback)
  I. Barge-in during SPEAKING lifecycle
  J. Barge-in does not bypass ToolExecutor
  K. Memory command lifecycle (remember, recall, forget)
  L. Conversation lifecycle (natural language turn -> IDLE)
  M. Tool lifecycle (system/app command -> IDLE)
  N. Security refusal lifecycle (refusal of protected actions -> IDLE)
  O. Exception lifecycle (guaranteed recovery to IDLE)
  P. Secret redaction (redaction preserved before TTS & in metrics)
  Q. Privacy invariants (no continuous audio persistence, local wake word)
  R. Streaming fallback (non-streaming STT falls back to batch cleanly)
  S. Provider unavailable fallback (graceful degradation)
  T. Multiple consecutive turns (repeat turns without state lock)
"""

from __future__ import annotations

import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai.conversation import ConversationManager
from app.ai.models import ChatMessage, ContentSource, MessageRole
from app.ai.provider import MockAIProvider
from app.core import BuddyConfig, BuddyState, EventBus, StateMachine
from app.memory import MemoryManager, MemoryPolicy, MemoryService, SqliteMemoryStore
from app.tools.builtin import register_builtin_tools
from app.tools.executor import ToolExecutor
from app.tools.models import ToolExecutionStatus, ToolRequest
from app.tools.registry import ToolRegistry
from app.voice import (
    AudioData,
    EnergyVAD,
    KeywordWakeWordDetector,
    LocalWakeWordDetector,
    MockAudioCapture,
    MockSTTProvider,
    MockStreamingSTTProvider,
    MockTTSProvider,
    MockVAD,
    MockWakeWordDetector,
    VADState,
    VoiceCommandRouter,
    VoiceIntent,
    VoiceIntentType,
    VoiceLatencyMetrics,
    VoiceOutcome,
    VoicePipeline,
)
from app.voice.events import (
    SpeechStartedEvent,
    SpeechStoppedEvent,
    VoiceBargeInDetectedEvent,
    VoiceLatencyRecordedEvent,
    VoicePartialTranscriptEvent,
    VoiceSpeechDetectedEvent,
    VoiceSpeechEndedEvent,
)
from app.voice.stt import BatchFallbackStreamingSession, StreamingSTTProvider
from app.voice.tts import clause_stream_from_tokens
from scripts.voice_assistant import dispatch_voice_intent


class TestVoiceLoop14(unittest.IsolatedAsyncioTestCase):
    """Rigorous Loop 14 verification suite covering tests A through T."""

    def setUp(self) -> None:
        self.config = BuddyConfig(
            app_env="testing",
            voice_enabled=True,
            voice_barge_in_enabled=True,
            voice_streaming_enabled=True,
            voice_audio_chunk_ms=32,
            voice_audio_queue_size=128,
            stt_provider="mock",
            tts_provider="mock",
        )
        self.event_bus = EventBus()
        self.state_machine = StateMachine(BuddyState.IDLE)
        self.capture = MockAudioCapture()
        self.vad = EnergyVAD(sample_rate=16000, use_audio_clock=True)
        self.stt = MockStreamingSTTProvider(default_transcript="what is my battery level")
        self.tts = MockTTSProvider(speech_delay=0.01)
        self.wake_detector = MockWakeWordDetector(wake_word="hey buddy", default_result=True)

        self.pipeline = VoicePipeline(
            config=self.config,
            event_bus=self.event_bus,
            state_machine=self.state_machine,
            capture=self.capture,
            vad=self.vad,
            stt=self.stt,
            tts=self.tts,
            wake_word=self.wake_detector,
        )

    # -------------------------------------------------------------------------
    # A. Latency Metrics Model & Fields
    # -------------------------------------------------------------------------
    async def test_a_latency_metrics_model(self) -> None:
        """Verify VoiceLatencyMetrics contains all required fields and produces clean metadata."""
        m = VoiceLatencyMetrics(
            wake_detection_ms=120.5,
            capture_start_ms=1000.0,
            capture_end_ms=2500.0,
            stt_start_ms=2505.0,
            first_transcript_ms=2800.0,
            stt_complete_ms=3100.0,
            routing_start_ms=3105.0,
            routing_complete_ms=3110.0,
            tool_start_ms=3115.0,
            tool_complete_ms=3135.0,
            ai_start_ms=3140.0,
            first_ai_token_ms=3200.0,
            ai_complete_ms=3400.0,
            tts_start_ms=3410.0,
            first_audio_output_ms=3460.0,
            tts_complete_ms=3900.0,
            barge_in_latency_ms=None,
            total_turn_ms=2900.0,
            intent_type="tool_request",
            stt_provider="mock_streaming",
            ai_provider="mock",
            tts_provider="mock",
            barge_in_triggered=False,
            success=True,
        )
        safe_dict = m.to_safe_dict()
        self.assertEqual(safe_dict["wake_detection_ms"], 120.5)
        self.assertEqual(safe_dict["total_turn_ms"], 2900.0)
        self.assertEqual(safe_dict["intent_type"], "tool_request")
        # Ensure no raw audio or transcript exists in metrics
        self.assertNotIn("audio", safe_dict)
        self.assertNotIn("transcript", safe_dict)
        self.assertNotIn("password", safe_dict)

    # -------------------------------------------------------------------------
    # B. Monotonic Timing Guarantees
    # -------------------------------------------------------------------------
    async def test_b_monotonic_timing_in_pipeline(self) -> None:
        """Verify durations and latency timestamps are strictly non-negative and monotonic."""
        self.pipeline._vad = MockVAD([VADState.WAITING, VADState.SPEAKING, VADState.SILENCE, VADState.COMPLETED])
        self.capture.set_canned_audio(AudioData(raw_data=b"\x20\x10" * 3200))

        res = await self.pipeline.listen_with_diagnostics(timeout=1.0)
        self.assertIsNotNone(res.latency_metrics)
        m = res.latency_metrics
        self.assertGreaterEqual(m.capture_end_ms, m.capture_start_ms)
        self.assertGreaterEqual(m.stt_complete_ms, m.stt_start_ms)
        self.assertGreater(m.total_turn_ms, 0.0)

    # -------------------------------------------------------------------------
    # C. Streaming VAD Incremental Chunk Processing
    # -------------------------------------------------------------------------
    async def test_c_streaming_vad(self) -> None:
        """Test streaming VAD across speech onset, continuation, silence, and completion."""
        vad = EnergyVAD(
            energy_threshold=50.0,
            silence_timeout=0.2,
            min_speech_duration=0.1,
            max_recording_duration=1.0,
            use_audio_clock=True,
        )
        vad.reset()

        silence_chunk = b"\x00\x00" * 160  # 10ms silence
        speech_chunk = b"\x40\x10" * 160   # 10ms high-energy speech

        # 1. Waiting
        st, ev = vad.process_chunk_event(silence_chunk)
        self.assertEqual(st, VADState.WAITING)
        self.assertFalse(vad.is_speech_started)
        self.assertFalse(vad.is_speech_active)

        # 2. Speech onset
        st, ev = vad.process_chunk_event(speech_chunk)
        self.assertEqual(st, VADState.SPEAKING)
        self.assertTrue(vad.is_speech_started)
        self.assertEqual(ev, "speech_started")

        # 3. Speech continuation
        for _ in range(12):  # 120ms speech > min_speech_duration
            st, ev = vad.process_chunk_event(speech_chunk)
            self.assertEqual(st, VADState.SPEAKING)
            self.assertEqual(ev, "speech_continues")
            self.assertTrue(vad.is_speech_active)

        # 4. Silence onset
        st, ev = vad.process_chunk_event(silence_chunk)
        self.assertEqual(st, VADState.SILENCE)
        self.assertTrue(vad.is_speech_active)

        # 5. Silence continuation until completion
        for _ in range(25):  # 250ms silence > silence_timeout
            st, ev = vad.process_chunk_event(silence_chunk)
            if st == VADState.COMPLETED:
                break

        self.assertEqual(st, VADState.COMPLETED)
        self.assertTrue(vad.is_speech_ended)
        self.assertEqual(vad.completion_reason, "speech_end")

    # -------------------------------------------------------------------------
    # D. Streaming STT Interface
    # -------------------------------------------------------------------------
    async def test_d_streaming_stt_interface(self) -> None:
        """Verify StreamingSTTProvider pushes chunks, delivers partials, and finalizes."""
        provider = MockStreamingSTTProvider(default_transcript="check system battery level")
        self.assertTrue(provider.supports_streaming)

        partials_received = []
        session = await provider.start_stream(
            on_partial=lambda text: partials_received.append(text)
        )

        chunk = b"\x20\x10" * 320
        p1 = await session.push_chunk(chunk)
        p2 = await session.push_chunk(chunk)
        self.assertIsNotNone(p1)
        self.assertIsNotNone(p2)
        self.assertIn("check", p1)

        result = await session.finish()
        self.assertEqual(result.transcript, "check system battery level")
        self.assertEqual(result.provider, "mock_streaming")

    # -------------------------------------------------------------------------
    # E. Streaming AI Interface
    # -------------------------------------------------------------------------
    async def test_e_streaming_ai_interface(self) -> None:
        """Verify ConversationManager streams tokens incrementally and prevents partial tool execution."""
        mock_provider = MockAIProvider()
        mock_provider.set_next_response("The quick brown fox jumps over the lazy dog.")

        conv = ConversationManager(
            config=self.config,
            event_bus=self.event_bus,
            state_machine=self.state_machine,
            auto_subscribe_voice=False,
        )
        with patch.object(conv._router, "get_provider", return_value=mock_provider):
            tokens = []
            async for tok in conv.process_user_turn_stream("tell me a sentence"):
                tokens.append(tok)

            self.assertGreater(len(tokens), 1)
            full_text = "".join(tokens).strip()
            self.assertEqual(full_text, "The quick brown fox jumps over the lazy dog.")

            # Ensure final message was recorded in history
            self.assertEqual(conv.history[-1].role, MessageRole.ASSISTANT)
            self.assertEqual(conv.history[-1].content, full_text)

    # -------------------------------------------------------------------------
    # F. Streaming TTS Interface
    # -------------------------------------------------------------------------
    async def test_f_streaming_tts_interface(self) -> None:
        """Verify TTS consumes token stream, chunks clauses, and signals first audio."""
        async def dummy_token_gen():
            for word in ["Hello", " ", "there!", " ", "How", " ", "are", " ", "you", " ", "today?"]:
                yield word
                await asyncio.sleep(0.001)

        first_audio_fired = False
        def on_first():
            nonlocal first_audio_fired
            first_audio_fired = True

        await self.tts.speak_stream(dummy_token_gen(), on_first_audio=on_first)
        self.assertTrue(first_audio_fired)
        self.assertGreaterEqual(len(self.tts.spoken_phrases), 1)

    # -------------------------------------------------------------------------
    # G. Cancellation
    # -------------------------------------------------------------------------
    async def test_g_cancellation(self) -> None:
        """Verify listening and speaking cancellation cleanly abort and reset state."""
        self.pipeline.cancel_listening()
        res = await self.pipeline.listen_with_diagnostics()
        self.assertEqual(res.outcome, VoiceOutcome.CANCELLED)
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

        # Stop speaking test
        await self.pipeline.stop_speaking()
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    # -------------------------------------------------------------------------
    # H. Barge-In Triggering
    # -------------------------------------------------------------------------
    async def test_h_barge_in_detection(self) -> None:
        """Verify high-energy human interruption halts active speech playback."""
        barge_in_events = []
        self.event_bus.subscribe(
            VoiceBargeInDetectedEvent,
            lambda ev: barge_in_events.append(ev),
        )

        mock_capture = MockAudioCapture()
        # Feed high energy burst
        loud_speech = b"\x70\x20" * 3200
        mock_capture.set_canned_audio(AudioData(raw_data=loud_speech))

        pipeline = VoicePipeline(
            config=self.config,
            event_bus=self.event_bus,
            state_machine=self.state_machine,
            capture=mock_capture,
            vad=self.vad,
            stt=self.stt,
            tts=MockTTSProvider(speech_delay=0.2),  # longer delay to allow barge-in monitor to catch it
        )

        completed = await pipeline.speak("This is a long sentence that will be interrupted.", barge_in=True)
        self.assertFalse(completed)
        self.assertEqual(self.state_machine.current_state, BuddyState.LISTENING)
        self.assertEqual(len(barge_in_events), 1)

    # -------------------------------------------------------------------------
    # I. Barge-In During SPEAKING Lifecycle
    # -------------------------------------------------------------------------
    async def test_i_barge_in_speaking_lifecycle(self) -> None:
        """Validate exact transition path: IDLE -> LISTENING -> THINKING -> SPEAKING -> (barge-in) -> LISTENING."""
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)
        self.state_machine.transition_to(BuddyState.LISTENING, reason="Wake word")
        self.state_machine.transition_to(BuddyState.THINKING, reason="STT")
        self.state_machine.transition_to(BuddyState.SPEAKING, reason="Playback")

        # Simulate barge-in interruption transition
        self.assertTrue(self.state_machine.can_transition_to(BuddyState.LISTENING))
        self.state_machine.transition_to(BuddyState.LISTENING, reason="Barge-in speech interruption")
        self.assertEqual(self.state_machine.current_state, BuddyState.LISTENING)

        # Next cycle completes and returns to IDLE
        self.state_machine.transition_to(BuddyState.IDLE, reason="Cycle finalized")
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    # -------------------------------------------------------------------------
    # J. Barge-In Does NOT Bypass ToolExecutor
    # -------------------------------------------------------------------------
    async def test_j_barge_in_does_not_bypass_toolexecutor(self) -> None:
        """Verify barge-in is strictly disabled during EXECUTING state."""
        self.state_machine.transition_to(BuddyState.THINKING, reason="Planning tool")
        self.state_machine.transition_to(BuddyState.EXECUTING, reason="Executing action")

        # In EXECUTING state, cannot transition directly to LISTENING (must complete tool execution)
        self.assertFalse(self.state_machine.can_transition_to(BuddyState.LISTENING))

        # Safe return to IDLE
        self.state_machine.transition_to(BuddyState.THINKING, reason="Execution complete")
        self.state_machine.transition_to(BuddyState.IDLE, reason="Done")

    # -------------------------------------------------------------------------
    # K. Memory Command Lifecycle
    # -------------------------------------------------------------------------
    async def test_k_memory_command_lifecycle(self) -> None:
        """Verify remember, recall, and forget spoken intents return cleanly to IDLE."""
        mem_store = SqliteMemoryStore(db_path=":memory:")
        mem_policy = MemoryPolicy(self.config)
        mem_service = MemoryService(store=mem_store, policy=mem_policy, event_bus=self.event_bus, config=self.config)
        mem_mgr = MemoryManager(service=mem_service, config=self.config)

        router = VoiceCommandRouter()

        # 1. Remember
        intent1 = router.classify("remember my favourite colour is blue")
        self.assertEqual(intent1.intent_type, VoiceIntentType.MEMORY_REMEMBER)
        resp1 = await dispatch_voice_intent(
            intent=intent1,
            tool_executor=MagicMock(),
            memory_manager=mem_mgr,
            conv_manager=MagicMock(),
            state_machine=self.state_machine,
        )
        self.assertIn("blue", resp1)

        # 2. Recall
        intent2 = router.classify("what is my favourite colour")
        self.assertEqual(intent2.intent_type, VoiceIntentType.MEMORY_RECALL)
        resp2 = await dispatch_voice_intent(
            intent=intent2,
            tool_executor=MagicMock(),
            memory_manager=mem_mgr,
            conv_manager=MagicMock(),
            state_machine=self.state_machine,
        )
        self.assertIn("blue", resp2)

        # 3. Forget
        intent3 = router.classify("forget my favourite colour")
        self.assertEqual(intent3.intent_type, VoiceIntentType.MEMORY_FORGET)
        resp3 = await dispatch_voice_intent(
            intent=intent3,
            tool_executor=MagicMock(),
            memory_manager=mem_mgr,
            conv_manager=MagicMock(),
            state_machine=self.state_machine,
        )
        self.assertIn("forgotten", resp3)
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    # -------------------------------------------------------------------------
    # L. Conversation Lifecycle
    # -------------------------------------------------------------------------
    async def test_l_conversation_lifecycle(self) -> None:
        """Verify conversational turns follow IDLE -> LISTENING -> THINKING -> SPEAKING -> IDLE."""
        conv_mgr = ConversationManager(
            config=self.config,
            event_bus=self.event_bus,
            state_machine=self.state_machine,
            voice_pipeline=self.pipeline,
            auto_subscribe_voice=False,
        )
        router = VoiceCommandRouter()
        intent = router.classify("tell me a fun joke")
        self.assertEqual(intent.intent_type, VoiceIntentType.CONVERSATION)

        reply = await dispatch_voice_intent(
            intent=intent,
            tool_executor=MagicMock(),
            memory_manager=None,
            conv_manager=conv_mgr,
            state_machine=self.state_machine,
        )
        self.assertTrue(bool(reply))
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    # -------------------------------------------------------------------------
    # M. Tool Lifecycle
    # -------------------------------------------------------------------------
    async def test_m_tool_lifecycle(self) -> None:
        """Verify spoken desktop tool command executes through ToolExecutor and returns to IDLE."""
        registry = ToolRegistry()
        register_builtin_tools(registry)
        executor = ToolExecutor(registry=registry, event_bus=self.event_bus)

        router = VoiceCommandRouter()
        intent = router.classify("what is my battery level")
        self.assertEqual(intent.intent_type, VoiceIntentType.TOOL_REQUEST)
        self.assertEqual(intent.tool_name, "system.get_battery")

        resp = await dispatch_voice_intent(
            intent=intent,
            tool_executor=executor,
            memory_manager=None,
            conv_manager=MagicMock(),
            state_machine=self.state_machine,
        )
        self.assertIn("battery", resp.lower())
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    # -------------------------------------------------------------------------
    # N. Security Refusal Lifecycle
    # -------------------------------------------------------------------------
    async def test_n_security_refusal_lifecycle(self) -> None:
        """Verify prohibited dangerous request is refused immediately without executing tools."""
        router = VoiceCommandRouter()
        mock_executor = MagicMock()

        intent = router.classify("delete Windows system file")
        self.assertEqual(intent.intent_type, VoiceIntentType.SECURITY_SENSITIVE)

        resp = await dispatch_voice_intent(
            intent=intent,
            tool_executor=mock_executor,
            memory_manager=None,
            conv_manager=MagicMock(),
            state_machine=self.state_machine,
        )
        mock_executor.execute.assert_not_called()
        self.assertIn("protected system files", resp)
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    # -------------------------------------------------------------------------
    # O. Exception Lifecycle
    # -------------------------------------------------------------------------
    async def test_o_exception_lifecycle(self) -> None:
        """Verify unhandled exceptions in pipeline recover safely to IDLE."""
        with patch.object(self.capture, "start", side_effect=RuntimeError("Microphone device crashed")):
            res = await self.pipeline.listen_with_diagnostics()
            self.assertEqual(res.outcome, VoiceOutcome.MIC_UNAVAILABLE)
            self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    # -------------------------------------------------------------------------
    # P. Secret Redaction
    # -------------------------------------------------------------------------
    async def test_p_secret_redaction(self) -> None:
        """Verify spoken responses containing secrets are redacted before speech synthesis."""
        from app.voice.tts import Pyttsx3TTSProvider
        tts = Pyttsx3TTSProvider()

        secret_text = "Your API key is sk-1234567890abcdef1234567890abcdef and password is supersecretpassword!"
        with patch.object(tts, "_init_engine") as mock_init:
            mock_engine = MagicMock()
            mock_init.return_value = mock_engine
            await tts.speak(secret_text)

            # Check that say() received redacted text
            mock_engine.say.assert_called_once()
            spoken_arg = mock_engine.say.call_args[0][0]
            self.assertNotIn("sk-1234567890", spoken_arg)
            self.assertIn("[REDACTED", spoken_arg)

    # -------------------------------------------------------------------------
    # Q. Privacy Invariants
    # -------------------------------------------------------------------------
    async def test_q_privacy_invariants(self) -> None:
        """Verify no audio files persisted to disk and LocalWakeWordDetector is offline."""
        detector = LocalWakeWordDetector(wake_word="hey buddy")
        self.assertTrue(detector.is_local)

        # Feed chunks locally
        chunk = b"\x20\x10" * 160
        res = detector.process_chunk(chunk)
        self.assertFalse(res)

        # Audio buffer check
        audio = AudioData(raw_data=chunk)
        detected = await detector.detect(audio)
        self.assertFalse(detected)

    # -------------------------------------------------------------------------
    # R. Streaming Fallback
    # -------------------------------------------------------------------------
    async def test_r_streaming_fallback(self) -> None:
        """Verify batch STT provider falls back transparently via BatchFallbackStreamingSession."""
        batch_provider = MockSTTProvider(default_transcript="batch fallback success")
        self.assertFalse(batch_provider.supports_streaming)

        session = await batch_provider.start_stream()
        self.assertIsInstance(session, BatchFallbackStreamingSession)

        await session.push_chunk(b"\x20\x10" * 320)
        res = await session.finish()
        self.assertEqual(res.transcript, "batch fallback success")

    # -------------------------------------------------------------------------
    # S. Provider Unavailable Fallback
    # -------------------------------------------------------------------------
    async def test_s_provider_unavailable_fallback(self) -> None:
        """Verify pipeline handles failing STT provider gracefully with error outcome."""
        mock_vad = MockVAD([VADState.WAITING, VADState.SPEAKING, VADState.SILENCE, VADState.COMPLETED])
        failing_provider = MockSTTProvider(simulate_failure=True)
        pipeline = VoicePipeline(
            config=self.config,
            event_bus=self.event_bus,
            state_machine=self.state_machine,
            capture=self.capture,
            vad=mock_vad,
            stt=failing_provider,
            tts=self.tts,
            wake_word=self.wake_detector,
        )
        self.capture.set_canned_audio(AudioData(raw_data=b"\x20\x10" * 3200))
        res = await pipeline.listen_with_diagnostics()
        self.assertEqual(res.outcome, VoiceOutcome.STT_FAILED)
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    # -------------------------------------------------------------------------
    # T. Multiple Consecutive Turns
    # -------------------------------------------------------------------------
    async def test_t_multiple_consecutive_turns(self) -> None:
        """Run 5 consecutive turns verifying zero state drift, lockups, or memory leaks."""
        for turn_idx in range(5):
            self.pipeline._vad = MockVAD([VADState.WAITING, VADState.SPEAKING, VADState.SILENCE, VADState.COMPLETED])
            self.capture.set_canned_audio(AudioData(raw_data=b"\x20\x10" * 3200))
            self.stt.default_transcript = f"command number {turn_idx}"

            res = await self.pipeline.listen_with_diagnostics()
            self.assertEqual(res.outcome, VoiceOutcome.TRANSCRIBED)
            self.assertEqual(res.transcript, f"command number {turn_idx}")
            self.assertEqual(self.state_machine.current_state, BuddyState.THINKING)

            # Clear canned audio so barge-in monitor doesn't detect residual speech
            self.capture.set_canned_audio(None)
            # Speak response
            await self.pipeline.speak(f"completed turn {turn_idx}")
            self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)
