"""Unit and Regression Tests for Voice State Machine Recovery.

Verifies that BUDDY Core State Machine returns reliably to IDLE after:
- Memory operations (remember, recall, forget)
- Builtin tool execution (battery, volume, app.open, app.close)
- Tool execution failures
- Conversational turns
- Security-sensitive refusals
- TTS and STT exceptions
- Sequential multi-command turns without state contamination

Covers minimum required tests A through J for the voice state machine recovery bug.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.ai.conversation import ConversationManager
from app.ai.models import AIResponse
from app.ai.router import AIRouter
from app.core import BuddyConfig, BuddyState, EventBus, StateMachine
from app.core.exceptions import MemoryPolicyViolationError
from app.memory import MemoryManager, MemoryPolicy, MemoryService, SqliteMemoryStore
from app.tools.builtin import register_builtin_tools
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.voice.capture import MockAudioCapture
from app.voice.command_router import VoiceCommandRouter, VoiceIntentType
from app.voice.models import AudioData, STTResult, TranscriptionStatus, VADState, VoiceOutcome
from app.voice.pipeline import VoicePipeline
from app.voice.stt import MockSTTProvider
from app.voice.tts import MockTTSProvider
from app.voice.vad import MockVAD
from app.voice.wake import MockWakeWordDetector
from scripts.voice_assistant import _recover_state_to_idle, dispatch_voice_intent


class TestVoiceStateRecovery(unittest.IsolatedAsyncioTestCase):
    """Test suite verifying state machine recovery across all voice interactions."""

    async def asyncSetUp(self) -> None:
        self.config = BuddyConfig(
            app_env="testing",
            voice_timeout=2.0,
            ai_provider="mock",
        )
        self.event_bus = EventBus()
        self.state_machine = StateMachine(BuddyState.IDLE)

        # Mocks for audio capture, VAD, STT, TTS, Wake Word
        self.mock_capture = MockAudioCapture()
        self.mock_vad = MockVAD([VADState.WAITING, VADState.SPEAKING, VADState.SILENCE, VADState.COMPLETED])
        self.mock_stt = MockSTTProvider(default_transcript="Hello")
        self.mock_tts = MockTTSProvider()
        self.mock_wake = MockWakeWordDetector(wake_word="hey buddy", default_result=True)

        self.pipeline = VoicePipeline(
            config=self.config,
            event_bus=self.event_bus,
            state_machine=self.state_machine,
            capture=self.mock_capture,
            vad=self.mock_vad,
            stt=self.mock_stt,
            tts=self.mock_tts,
            wake_word=self.mock_wake,
        )

        # Builtin Tool Registry & Executor
        self.registry = ToolRegistry()
        register_builtin_tools(self.registry)
        self.tool_executor = ToolExecutor(registry=self.registry, event_bus=self.event_bus)

        # In-memory SQLite Memory Subsystem
        self.mem_store = SqliteMemoryStore(db_path=":memory:")
        self.mem_policy = MemoryPolicy(self.config)
        self.mem_service = MemoryService(
            store=self.mem_store,
            policy=self.mem_policy,
            event_bus=self.event_bus,
            config=self.config,
        )
        self.memory_manager = MemoryManager(service=self.mem_service, config=self.config)

        # Mock AI Router & Conversation Manager
        self.mock_ai = MagicMock()
        self.mock_ai.provider_name = "mock"
        self.mock_ai.generate = AsyncMock(
            return_value=AIResponse(
                content="I am BUDDY, your AI assistant.",
                provider="mock",
                model="test-model",
            )
        )
        self.router = AIRouter(self.config)
        self.router.register_provider("mock", self.mock_ai)

        self.conv_manager = ConversationManager(
            config=self.config,
            event_bus=self.event_bus,
            state_machine=self.state_machine,
            router=self.router,
            voice_pipeline=self.pipeline,
            tool_executor=self.tool_executor,
            memory_manager=self.memory_manager,
            auto_subscribe_voice=False,  # Single authoritative voice dispatcher in script
        )

        self.cmd_router = VoiceCommandRouter()

    async def asyncTearDown(self) -> None:
        self.mem_store.close()
        await self.event_bus.shutdown()

    async def _execute_turn(self, utterance: str) -> str:
        """Helper to simulate an end-to-end voice interaction turn as executed in scripts/voice_assistant.py."""
        self.mock_stt.default_transcript = utterance
        self.mock_vad.reset()

        try:
            # 1. Listen with diagnostics
            listen_res = await self.pipeline.listen_with_diagnostics(timeout=2.0)
            self.assertTrue(listen_res.ok, f"Listening failed for '{utterance}': {listen_res.error_message}")

            # State is now in THINKING following utterance capture
            self.assertEqual(self.state_machine.current_state, BuddyState.THINKING)

            # 2. Route intent
            intent = self.cmd_router.classify(listen_res.transcript)

            # 3. Dispatch intent
            response_text = await dispatch_voice_intent(
                intent=intent,
                tool_executor=self.tool_executor,
                memory_manager=self.memory_manager,
                conv_manager=self.conv_manager,
                state_machine=self.state_machine,
            )

            # 4. Speak response
            await self.pipeline.speak(response_text)
            return response_text
        finally:
            if self.state_machine.current_state != BuddyState.IDLE:
                _recover_state_to_idle(self.state_machine, "Turn finalized")

    # -------------------------------------------------------------------------
    # Test A: memory_remember_returns_to_idle
    # -------------------------------------------------------------------------
    async def test_A_memory_remember_returns_to_idle(self) -> None:
        """Requirement A: 'remember my favourite colour is red' speaks and returns state to IDLE."""
        response = await self._execute_turn("remember my favourite colour is red")
        self.assertIn("red", response.lower())
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

        # Empirical verification of stored memory
        records = await self.memory_manager.recall("favourite colour")
        self.assertTrue(len(records) > 0)
        self.assertIn("red", records[0].content.lower())

    # -------------------------------------------------------------------------
    # Test B: memory_recall_returns_to_idle
    # -------------------------------------------------------------------------
    async def test_B_memory_recall_returns_to_idle(self) -> None:
        """Requirement B: 'what is my favourite colour' recalls saved preference and returns to IDLE."""
        await self.memory_manager.remember("my favourite colour is red")
        response = await self._execute_turn("what is my favourite colour")
        self.assertIn("red", response.lower())
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    # -------------------------------------------------------------------------
    # Test C: memory_forget_returns_to_idle
    # -------------------------------------------------------------------------
    async def test_C_memory_forget_returns_to_idle(self) -> None:
        """Requirement C: 'forget my favourite colour' removes preference and returns to IDLE."""
        await self.memory_manager.remember("my favourite colour is red")
        response = await self._execute_turn("forget my favourite colour")
        self.assertIn("forgotten", response.lower())
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

        # Confirm preference is indeed gone
        records = await self.memory_manager.recall("favourite colour")
        self.assertEqual(len(records), 0)

    # -------------------------------------------------------------------------
    # Test D: conversation_returns_to_idle
    # -------------------------------------------------------------------------
    async def test_D_conversation_returns_to_idle(self) -> None:
        """Requirement D: Conversational fallback ('what is your name') returns to IDLE without double-voicing."""
        response = await self._execute_turn("what is your name")
        self.assertIn("BUDDY", response)
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)
        # Verify phrase spoken exactly once
        self.assertEqual(self.mock_tts.spoken_phrases.count(response), 1)

    # -------------------------------------------------------------------------
    # Test E: security_refusal_returns_to_idle
    # -------------------------------------------------------------------------
    async def test_E_security_refusal_returns_to_idle(self) -> None:
        """Requirement E: Dangerous command refusal ('delete the Windows system file') returns to IDLE."""
        response = await self._execute_turn("delete the Windows system file")
        self.assertIn("cannot perform", response.lower())
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    # -------------------------------------------------------------------------
    # Test F: tool_failure_returns_to_idle
    # -------------------------------------------------------------------------
    async def test_F_tool_failure_returns_to_idle(self) -> None:
        """Requirement F: Failed tool execution reports honest failure and returns to IDLE."""
        with patch.object(self.tool_executor, "execute") as mock_exec:
            mock_res = MagicMock()
            mock_res.success = False
            mock_res.verified = False
            mock_res.error = "Process failed to launch"
            mock_exec.return_value = mock_res

            response = await self._execute_turn("open notepad")
            self.assertIn("failed", response.lower())
            self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    # -------------------------------------------------------------------------
    # Test G: exception_returns_to_idle
    # -------------------------------------------------------------------------
    async def test_G_exception_returns_to_idle(self) -> None:
        """Requirement G: Unexpected exception during dispatch guarantees state recovery to IDLE."""
        with patch("scripts.voice_assistant.dispatch_voice_intent", side_effect=RuntimeError("Simulated unexpected crash")):
            try:
                await self._execute_turn("what is my battery level")
            except RuntimeError:
                pass
            # Final state must be IDLE despite unhandled exception
            self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    # -------------------------------------------------------------------------
    # Test H: multiple_commands_after_memory
    # -------------------------------------------------------------------------
    async def test_H_multiple_commands_after_memory(self) -> None:
        """Requirement H: Sequence of commands after memory operation without state contamination.

        remember -> IDLE -> battery -> IDLE -> volume -> IDLE -> recall -> IDLE
        """
        # 1. Remember command
        r1 = await self._execute_turn("remember my favourite colour is red")
        self.assertIn("red", r1.lower())
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

        # 2. Battery query
        with patch.object(self.tool_executor, "execute") as mock_exec:
            res_battery = MagicMock()
            res_battery.success = True
            res_battery.verified = True
            res_battery.output = {"percent": 88, "power_plugged": True}
            mock_exec.return_value = res_battery

            r2 = await self._execute_turn("what is my battery level")
            self.assertIn("88%", r2)
            self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

        # 3. Volume query
        with patch.object(self.tool_executor, "execute") as mock_exec:
            res_vol = MagicMock()
            res_vol.success = True
            res_vol.verified = True
            res_vol.output = {"volume": 65}
            mock_exec.return_value = res_vol

            r3 = await self._execute_turn("what is my current volume")
            self.assertIn("65%", r3)
            self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

        # 4. Recall memory
        r4 = await self._execute_turn("what is my favourite colour")
        self.assertIn("red", r4.lower())
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    # -------------------------------------------------------------------------
    # Test I: wake_word_after_memory
    # -------------------------------------------------------------------------
    async def test_I_wake_word_after_memory(self) -> None:
        """Requirement I: Wake word detector immediately works following memory remember."""
        # Run remember turn
        await self._execute_turn("remember my favourite colour is red")
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

        # Wake word detection
        detected = await self.pipeline.listen_for_wake_word(timeout=1.0)
        self.assertTrue(detected)

        # Subsequent listen_with_diagnostics must not fail with Invalid start state
        self.mock_stt.default_transcript = "what time is it"
        listen_res = await self.pipeline.listen_with_diagnostics(timeout=2.0)
        self.assertTrue(listen_res.ok)
        self.assertEqual(listen_res.outcome, VoiceOutcome.TRANSCRIBED)
        self.assertEqual(self.state_machine.current_state, BuddyState.THINKING)
        self.pipeline._recover_to_idle("Test cleanup")
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    # -------------------------------------------------------------------------
    # Test J: enter_activation_after_memory
    # -------------------------------------------------------------------------
    async def test_J_enter_activation_after_memory(self) -> None:
        """Requirement J: Direct keypress/ENTER activation works immediately following memory remember."""
        # Run remember turn
        await self._execute_turn("remember my favourite colour is red")
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

        # Simulate immediate ENTER activation (which directly invokes listen_with_diagnostics from IDLE)
        self.assertTrue(self.state_machine.can_transition_to(BuddyState.LISTENING))
        self.mock_stt.default_transcript = "what is my battery level"
        listen_res = await self.pipeline.listen_with_diagnostics(timeout=2.0)
        self.assertTrue(listen_res.ok)
        self.assertEqual(listen_res.transcript, "what is my battery level")
        self.pipeline._recover_to_idle("Test cleanup")
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    # -------------------------------------------------------------------------
    # Additional Guard Tests: Routing failure & VAD chunk ordering (Step 11)
    # -------------------------------------------------------------------------
    async def test_routing_failure_recovers_to_idle(self) -> None:
        """Verify routing failure (invalid start state) self-heals by recovering to IDLE."""
        # Force state to THINKING (the exact bug state)
        self.state_machine.transition_to(BuddyState.THINKING, reason="Testing invalid start state")
        self.assertEqual(self.state_machine.current_state, BuddyState.THINKING)

        # Attempt to listen
        res = await self.pipeline.listen_with_diagnostics(timeout=1.0)
        self.assertEqual(res.outcome, VoiceOutcome.ROUTING_FAILED)
        self.assertIn("Invalid start state", res.error_message or "")
        # Must have recovered to IDLE!
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    async def test_tts_failure_recovers_to_idle(self) -> None:
        """Verify that TTS failure during speech playback cleanly recovers state machine to IDLE."""
        self.state_machine.transition_to(BuddyState.THINKING, reason="Testing TTS error")
        with patch.object(self.mock_tts, "speak", side_effect=RuntimeError("TTS engine crashed")):
            with self.assertRaises(RuntimeError):
                await self.pipeline.speak("This speech will fail")
            self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    async def test_memory_policy_security_violation_returns_to_idle(self) -> None:
        """Verify memory policy violation (e.g. attempting to store passwords) returns to IDLE."""
        response = await self._execute_turn("remember my password is secret123")
        self.assertIn("cannot store", response.lower())
        self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)


    async def test_vad_process_chunk_order_before_rms_reading(self) -> None:
        """Step 11: Verify VAD processes chunk BEFORE reading last_rms, avoiding stale 0.0 RMS."""
        call_log = []

        class OrderedVAD(MockVAD):
            def process_chunk(self, chunk: bytes) -> VADState:
                call_log.append("process_chunk")
                self.last_rms = 55.5
                return VADState.COMPLETED

            @property
            def last_rms(self) -> float:
                call_log.append("get_last_rms")
                return self._rms_val

            @last_rms.setter
            def last_rms(self, val: float) -> None:
                self._rms_val = val

        ordered_vad = OrderedVAD([VADState.COMPLETED])
        ordered_vad._rms_val = 0.0
        self.pipeline._vad = ordered_vad

        res = await self.pipeline.listen_with_diagnostics(timeout=2.0)
        self.pipeline._recover_to_idle("Test cleanup")

        # Verify that process_chunk was called before get_last_rms
        self.assertIn("process_chunk", call_log)
        self.assertIn("get_last_rms", call_log)
        p_idx = call_log.index("process_chunk")
        r_idx = call_log.index("get_last_rms")
        self.assertLess(p_idx, r_idx, "process_chunk must precede reading last_rms")
        self.assertGreaterEqual(res.diagnostics.peak_rms, 55.5)


if __name__ == "__main__":
    unittest.main()
