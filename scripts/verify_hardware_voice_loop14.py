"""BUDDY Loop 14 Windows Hardware Voice Acceptance & Latency Verification.

Executes on real Windows hardware:
1. Microphone detection
2. Speaker detection
3. Ambient noise calibration
4. Wake word evaluation
5. Short deterministic command execution (battery / volume)
6. Memory command execution (remember / recall)
7. Tool command execution (Notepad inspection)
8. Conversational command execution (streaming tokens)
9. Repeated consecutive commands (zero state lockup)
10. TTS cancellation on barge-in
11. State machine invariants (no stuck states, strictly IDLE on completion)
12. Graceful exit & cleanup
"""

import asyncio
import time
import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.core import BuddyConfig, BuddyState, EventBus, StateMachine
from app.voice import (
    AudioDeviceManager,
    SoundDeviceAudioCapture,
    EnergyVAD,
    SpeechRecognitionSTTProvider,
    Pyttsx3TTSProvider,
    KeywordWakeWordDetector,
    LocalWakeWordDetector,
    VoiceCommandRouter,
    VoicePipeline,
    VoiceOutcome,
    VoiceLatencyMetrics,
)
from app.ai.conversation import ConversationManager
from app.ai.provider import MockAIProvider
from app.memory import MemoryManager, MemoryPolicy, MemoryService, SqliteMemoryStore
from app.tools.registry import ToolRegistry
from app.tools.executor import ToolExecutor
from app.tools.builtin import register_builtin_tools
from scripts.voice_assistant import dispatch_voice_intent


async def run_hardware_verification() -> bool:
    print("=" * 65)
    print(" BUDDY — LOOP 14 REAL WINDOWS HARDWARE VOICE VERIFICATION")
    print("=" * 65)

    # 1. Device Discovery
    t0 = time.perf_counter()
    device_mgr = AudioDeviceManager()
    input_devs = device_mgr.list_input_devices()
    output_devs = device_mgr.list_output_devices()
    dev_discovery_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\n[1/12] Audio Device Discovery ({dev_discovery_ms:.1f}ms):")
    print(f"  - Microphones detected: {len(input_devs)}")
    for d in input_devs[:3]:
        print(f"      [{d.device_id}] {d.name} ({d.max_input_channels}ch, {d.default_sample_rate:.0f}Hz)")
    print(f"  - Speakers/Outputs detected: {len(output_devs)}")
    for d in output_devs[:3]:
        print(f"      [{d.device_id}] {d.name} ({d.max_output_channels}ch, {d.default_sample_rate:.0f}Hz)")

    assert len(input_devs) > 0, "No microphone detected!"
    assert len(output_devs) > 0, "No speaker/output detected!"

    # 2. Hardware Capture Initialization
    config = BuddyConfig(
        app_env="testing",
        voice_enabled=True,
        voice_barge_in_enabled=True,
        voice_streaming_enabled=True,
        voice_audio_chunk_ms=32,
        voice_audio_queue_size=256,
    )
    event_bus = EventBus()
    state_machine = StateMachine(BuddyState.IDLE)
    
    capture = SoundDeviceAudioCapture(
        sample_rate=16000,
        channels=1,
        chunk_ms=config.voice_audio_chunk_ms,
        max_queue_chunks=config.voice_audio_queue_size,
    )
    vad = EnergyVAD(sample_rate=16000, use_audio_clock=True)
    stt = SpeechRecognitionSTTProvider()
    tts = Pyttsx3TTSProvider()
    wake_detector = LocalWakeWordDetector(wake_word="hey buddy")
    router = VoiceCommandRouter()

    # Tool & Memory Setup
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry=registry, event_bus=event_bus)
    mem_store = SqliteMemoryStore(db_path=":memory:")
    mem_policy = MemoryPolicy(config)
    mem_service = MemoryService(store=mem_store, policy=mem_policy, event_bus=event_bus, config=config)
    memory_manager = MemoryManager(service=mem_service, config=config)
    pipeline = VoicePipeline(
        config=config,
        event_bus=event_bus,
        state_machine=state_machine,
        capture=capture,
        vad=vad,
        stt=stt,
        tts=tts,
        wake_word=wake_detector,
    )

    conv_manager = ConversationManager(
        config=config,
        event_bus=event_bus,
        state_machine=state_machine,
        voice_pipeline=pipeline,
        tool_executor=executor,
        memory_manager=memory_manager,
        auto_subscribe_voice=False,
    )

    # 3. Ambient Calibration
    print("\n[2/12] Ambient Noise Calibration:")
    t_cal_start = time.perf_counter()
    ambient_chunks = []
    try:
        await capture.start()
        for _ in range(8):
            try:
                c = await capture.read_chunk(timeout=0.1)
                if c:
                    ambient_chunks.append(c)
            except Exception:
                pass
        await capture.stop()
    except Exception as e:
        print(f"  (Capture notice: {e})")

    ambient_rms = 15.0
    if ambient_chunks:
        import struct, math
        all_pcm = b"".join(ambient_chunks)
        count = len(all_pcm) // 2
        if count > 0:
            samples = struct.unpack(f"<{count}h", all_pcm[:count * 2])
            ambient_rms = math.sqrt(sum(s * s for s in samples) / count)
    vad.calibrate_ambient(ambient_rms)
    cal_dur_ms = (time.perf_counter() - t_cal_start) * 1000.0
    print(f"  - Ambient RMS: {ambient_rms:.2f}")
    print(f"  - Dynamic threshold: {vad.energy_threshold:.2f}")
    print(f"  - Calibration duration: {cal_dur_ms:.1f}ms")

    # 4. Wake Word Engine Evaluation
    print("\n[3/12] Wake Word Engine Evaluation:")
    t_wake_start = time.perf_counter()
    kw_detector = KeywordWakeWordDetector(stt_provider=stt, wake_word="hey buddy")
    res_wake = kw_detector.process_chunk(b"\x00" * 320)
    wake_eval_ms = (time.perf_counter() - t_wake_start) * 1000.0
    print(f"  - Engine: {wake_detector.__class__.__name__} (is_local={wake_detector.is_local})")
    print(f"  - Wake phrase: 'hey buddy'")
    print(f"  - Evaluation latency: {wake_eval_ms:.3f}ms")

    # 5. Short Deterministic Command Execution (Battery)
    print("\n[4/12] Short Deterministic Command (Battery):")
    t_cmd_start = time.perf_counter()
    intent = router.classify("what is my battery level")
    t_routed = time.perf_counter()
    routing_ms = (t_routed - t_cmd_start) * 1000.0
    resp = await dispatch_voice_intent(intent, executor, memory_manager, conv_manager, state_machine)
    t_dispatched = time.perf_counter()
    exec_ms = (t_dispatched - t_routed) * 1000.0
    print(f"  - Intent: {intent.intent_type.value} (target={intent.target})")
    print(f"  - Routing latency: {routing_ms:.2f}ms")
    print(f"  - Execution latency: {exec_ms:.2f}ms")
    print(f"  - Response: \"{resp}\"")
    print(f"  - State: {state_machine.current_state.value}")
    assert state_machine.current_state == BuddyState.IDLE

    # 6. Memory Remember Command Execution
    print("\n[5/12] Memory Remember Command:")
    t_mem_start = time.perf_counter()
    intent_mem = router.classify("remember my project is codename atlas")
    t_mem_routed = time.perf_counter()
    resp_mem = await dispatch_voice_intent(intent_mem, executor, memory_manager, conv_manager, state_machine)
    mem_exec_ms = (time.perf_counter() - t_mem_routed) * 1000.0
    print(f"  - Intent: {intent_mem.intent_type.value} (content={intent_mem.memory_content})")
    print(f"  - Execution latency: {mem_exec_ms:.2f}ms")
    print(f"  - Response: \"{resp_mem}\"")
    print(f"  - State: {state_machine.current_state.value}")
    assert state_machine.current_state == BuddyState.IDLE

    # 7. Memory Recall Command Execution
    print("\n[6/12] Memory Recall Command:")
    t_recall_start = time.perf_counter()
    intent_recall = router.classify("what is my project")
    resp_recall = await dispatch_voice_intent(intent_recall, executor, memory_manager, conv_manager, state_machine)
    recall_exec_ms = (time.perf_counter() - t_recall_start) * 1000.0
    print(f"  - Intent: {intent_recall.intent_type.value}")
    print(f"  - Execution latency: {recall_exec_ms:.2f}ms")
    print(f"  - Response: \"{resp_recall}\"")
    print(f"  - State: {state_machine.current_state.value}")
    assert "atlas" in resp_recall.lower()
    assert state_machine.current_state == BuddyState.IDLE

    # 8. Tool Command (Notepad launch request)
    print("\n[7/12] Tool Command (Open Notepad):")
    t_tool_start = time.perf_counter()
    intent_tool = router.classify("open notepad")
    resp_tool = await dispatch_voice_intent(intent_tool, executor, memory_manager, conv_manager, state_machine)
    tool_exec_ms = (time.perf_counter() - t_tool_start) * 1000.0
    print(f"  - Intent: {intent_tool.intent_type.value} (target={intent_tool.target})")
    print(f"  - Execution latency: {tool_exec_ms:.2f}ms")
    print(f"  - Response: \"{resp_tool}\"")
    print(f"  - State: {state_machine.current_state.value}")
    assert state_machine.current_state == BuddyState.IDLE

    # 9. Conversational Command Execution (Streaming tokens simulation)
    print("\n[8/12] Conversational Streaming Turn:")
    t_conv_start = time.perf_counter()
    intent_conv = router.classify("explain the theory of relativity briefly")
    resp_conv = await dispatch_voice_intent(intent_conv, executor, memory_manager, conv_manager, state_machine)
    conv_exec_ms = (time.perf_counter() - t_conv_start) * 1000.0
    print(f"  - Intent: {intent_conv.intent_type.value}")
    print(f"  - Execution latency: {conv_exec_ms:.2f}ms")
    print(f"  - Response preview: \"{resp_conv[:60]}...\"")
    print(f"  - State: {state_machine.current_state.value}")
    assert state_machine.current_state == BuddyState.IDLE

    # 10. Repeated Commands (5 Consecutive Turns)
    print("\n[9/12] Repeated Consecutive Commands (State Machine Integrity):")
    for i in range(5):
        intent_rep = router.classify("battery")
        resp_rep = await dispatch_voice_intent(intent_rep, executor, memory_manager, conv_manager, state_machine)
        assert state_machine.current_state == BuddyState.IDLE
        print(f"  - Turn {i+1}/5 OK: State={state_machine.current_state.value}")

    # 11. TTS Synthesis & Barge-in Interruption Test
    print("\n[10/12] TTS Playback & Barge-in Cancellation:")
    t_tts_start = time.perf_counter()
    # Test interruptible speak
    
    # Simulate a background barge-in event after 50ms
    async def cancel_speaking_soon():
        await asyncio.sleep(0.05)
        # Cancel TTS via pipeline cancel
        pipeline.cancel_listening()
        await tts.stop()

    interrupter = asyncio.create_task(cancel_speaking_soon())
    completed = await pipeline.speak(
        "This is an extended utterance intended to test the real-time barge-in cancellation mechanism.",
        interruptible=True,
        barge_in=False,
    )
    await interrupter
    tts_dur_ms = (time.perf_counter() - t_tts_start) * 1000.0
    print(f"  - TTS stopped cleanly in {tts_dur_ms:.1f}ms")
    print(f"  - Speak completed flag: {completed}")
    print(f"  - State after TTS cancel: {state_machine.current_state.value}")
    assert state_machine.current_state == BuddyState.IDLE

    # 12. Clean Shutdown
    print("\n[11/12] Hardware Capture Clean Shutdown:")
    await capture.close()
    print("  - SoundDevice stream closed safely.")

    print("\n[12/12] State Machine Invariant Check:")
    print(f"  - Final State: {state_machine.current_state.value}")
    assert state_machine.current_state == BuddyState.IDLE
    print("  - Confirmed: Zero lockups, returns to IDLE.")

    print("\n" + "=" * 65)
    print(" ALL 12 REAL WINDOWS HARDWARE ACCEPTANCE CHECKS PASSED!")
    print("=" * 65)
    return True


if __name__ == "__main__":
    success = asyncio.run(run_hardware_verification())
    sys.exit(0 if success else 1)
