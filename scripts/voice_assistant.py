"""BUDDY Live Interactive Voice Assistant.

Run directly via:
    python scripts/voice_assistant.py

Features:
- Live voice activation via wake word ("Hey BUDDY") or pressing [ENTER] / [SPACE].
- Real-time microphone capture & Speech-to-Text transcription.
- Conversational turn execution with builtin Windows desktop tools.
- Text-to-Speech audio response playback via Windows pyttsx3.
"""

import asyncio
import datetime
import math
import os
import struct
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Ensure project root in sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.ai.conversation import ConversationManager
from app.core import BuddyConfig, BuddyState, EventBus, StateMachine
from app.core.exceptions import MemoryPolicyViolationError
from app.memory import MemoryManager, MemoryPolicy, MemoryService, SqliteMemoryStore
from app.tools.builtin import register_builtin_tools
from app.tools.executor import ToolExecutor
from app.tools.models import ToolExecutionStatus, ToolRequest
from app.tools.registry import ToolRegistry
from app.voice import (
    AudioDeviceManager,
    EnergyVAD,
    KeywordWakeWordDetector,
    Pyttsx3TTSProvider,
    SoundDeviceAudioCapture,
    SpeechRecognitionSTTProvider,
    VoiceCommandRouter,
    VoiceIntent,
    VoiceIntentType,
    VoicePipeline,
)


async def check_keyboard_activation() -> bool:
    """Non-blocking keyboard press detector on Windows."""
    try:
        import msvcrt

        while True:
            if msvcrt.kbhit():
                # Drain buffered keystrokes
                while msvcrt.kbhit():
                    msvcrt.getch()
                return True
            await asyncio.sleep(0.05)
    except Exception:
        await asyncio.sleep(8.0)
        return False


# Loop 15: the dispatcher now lives in app.desktop.dispatch so the console assistant
# and the persistent desktop runtime share a single implementation. These names are
# re-exported here for backward compatibility with existing tests and callers.
from app.desktop.dispatch import dispatch_voice_intent  # noqa: E402,F401
from app.desktop.dispatch import recover_state_to_idle as _recover_state_to_idle  # noqa: E402,F401


async def run_voice_assistant() -> None:
    print("=" * 72)
    print("           BUDDY LIVE INTERACTIVE VOICE ASSISTANT")
    print("=" * 72)

    config = BuddyConfig.load_from_env()
    event_bus = EventBus()
    state_machine = StateMachine(BuddyState.IDLE)
    device_mgr = AudioDeviceManager()

    default_mic = device_mgr.get_default_input_device()
    default_speaker = device_mgr.get_default_output_device()

    print(f"Microphone: {default_mic.name if default_mic else 'NOT DETECTED'}")
    print(f"Speaker:    {default_speaker.name if default_speaker else 'NOT DETECTED'}")
    print(f"Wake Word:  \"{config.wake_word}\"")
    print("=" * 72)

    if not default_mic:
        print("\n[ERROR] No active microphone detected. Please plug in a microphone.")
        return

    # 1. Initialize Hardware Voice Pipeline with low-latency settings
    capture = SoundDeviceAudioCapture(
        sample_rate=config.audio_sample_rate,
        channels=config.audio_channels,
        chunk_ms=config.voice_audio_chunk_ms,
        max_queue_chunks=config.voice_audio_queue_size,
        persistent=True,
    )
    vad = EnergyVAD(
        energy_threshold=getattr(config, "vad_energy_threshold", 60.0),
        silence_timeout=1.2,
        min_speech_duration=0.2,
        sample_rate=config.audio_sample_rate,
    )
    stt = SpeechRecognitionSTTProvider()
    tts = Pyttsx3TTSProvider()
    wake_detector = KeywordWakeWordDetector(stt_provider=stt, wake_word=config.wake_word)

    pipeline = VoicePipeline(
        config=config,
        event_bus=event_bus,
        state_machine=state_machine,
        device_manager=device_mgr,
        capture=capture,
        vad=vad,
        stt=stt,
        tts=tts,
        wake_word=wake_detector,
    )

    # 2. Ambient Noise Calibration
    print("\nCalibrating microphone ambient noise (0.5s)...")
    try:
        await capture.start()
        ambient_chunks = []
        for _ in range(8):
            try:
                c = await capture.read_chunk(timeout=0.2)
                ambient_chunks.append(c)
            except Exception:
                pass
        await capture.stop()

        if ambient_chunks:
            all_pcm = b"".join(ambient_chunks)
            count = len(all_pcm) // 2
            if count > 0:
                samples = struct.unpack(f"<{count}h", all_pcm[:count * 2])
                ambient_rms = math.sqrt(sum(s * s for s in samples) / count)
                vad.calibrate_ambient(ambient_rms)
                print(f"Room noise floor: {ambient_rms:.1f} RMS | Speech threshold: {vad.energy_threshold:.1f} RMS")
    except Exception as cal_err:
        print(f"Ambient calibration skipped ({cal_err}), threshold: {vad.energy_threshold:.1f} RMS")

    # 3. Initialize Tool Subsystem, Memory Manager & Conversation Manager
    registry = ToolRegistry()
    register_builtin_tools(registry)
    tool_executor = ToolExecutor(registry=registry, event_bus=event_bus)

    # Initialize Memory Subsystem
    try:
        mem_db_path = Path("data/buddy_memory.db")
        mem_db_path.parent.mkdir(parents=True, exist_ok=True)
        mem_store = SqliteMemoryStore(db_path=mem_db_path)
        mem_policy = MemoryPolicy(config)
        mem_service = MemoryService(store=mem_store, policy=mem_policy, event_bus=event_bus, config=config)
        memory_manager = MemoryManager(service=mem_service, config=config)
    except Exception as mem_init_err:
        print(f"Memory initialization notice: {mem_init_err}")
        memory_manager = None

    conv_manager = ConversationManager(
        config=config,
        event_bus=event_bus,
        state_machine=state_machine,
        voice_pipeline=pipeline,
        tool_executor=tool_executor,
        memory_manager=memory_manager,
        auto_subscribe_voice=False,
    )

    router = VoiceCommandRouter()

    # 4. Welcome Announcement
    welcome_text = "BUDDY voice assistant is online. How can I help you?"
    print(f"\nBUDDY: {welcome_text}")
    try:
        await pipeline.speak(welcome_text)
    except Exception as e:
        print(f"(Audio playback notice: {e})")

    print("\nInteraction options:")
    print("  1. Speak the wake word: 'Hey BUDDY', then give your command.")
    print("  2. Or press [ENTER] / [SPACE] to talk immediately.")
    print("  3. Say 'exit' or press Ctrl+C to terminate.\n")

    try:
        while True:
            try:
                print("Listening for wake word ('Hey BUDDY') or press [ENTER] to speak...")

                listen_task = asyncio.create_task(pipeline.listen_for_wake_word(timeout=8.0))
                key_task = asyncio.create_task(check_keyboard_activation())

                done, pending = await asyncio.wait(
                    [listen_task, key_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for t in pending:
                    t.cancel()
                    try:
                        await t
                    except (asyncio.CancelledError, Exception):
                        pass

                activated = False
                if listen_task in done:
                    try:
                        if listen_task.result():
                            print("\n[!] Wake word 'Hey BUDDY' detected!")
                            activated = True
                    except Exception:
                        pass

                if key_task in done and not activated:
                    try:
                        if key_task.result():
                            print("\n[!] Activated by keypress.")
                            activated = True
                    except Exception:
                        pass

                if activated:
                    try:
                        # Audible prompt
                        try:
                            await pipeline.speak("I'm listening.")
                        except Exception:
                            pass

                        print(">>> LISTENING FOR YOUR COMMAND (speak now)... <<<")
                        listen_res = await pipeline.listen_with_diagnostics(timeout=7.0)

                        if listen_res.ok and listen_res.transcript:
                            user_cmd = listen_res.transcript.strip()
                            lat_info = f"capture={listen_res.capture_latency:.2f}s, stt={listen_res.stt_latency:.2f}s"
                            if listen_res.latency_metrics:
                                m = listen_res.latency_metrics
                                lat_info += f" (turn={m.total_turn_ms:.0f}ms)"
                            print(f"\nYou said: \"{user_cmd}\" (latency: {lat_info})")

                            # Check exit commands
                            if user_cmd.lower() in ("exit", "quit", "goodbye", "bye", "shutdown"):
                                farewell = "Goodbye! Have a great day."
                                print(f"BUDDY: {farewell}")
                                await pipeline.speak(farewell)
                                break

                            # Classify spoken intent via typed VoiceCommandRouter
                            intent = router.classify(user_cmd)
                            print(f"[Router] Intent: {intent.intent_type.value} | target: {intent.target or intent.tool_name or 'n/a'}")

                            # Dispatch intent to appropriate subsystem (tool, memory, security, or conversation)
                            response_text = await dispatch_voice_intent(
                                intent=intent,
                                tool_executor=tool_executor,
                                memory_manager=memory_manager,
                                conv_manager=conv_manager,
                                state_machine=state_machine,
                            )
                            print(f"BUDDY: {response_text}\n")
                            completed = await pipeline.speak(response_text, interruptible=True, barge_in=True)
                            if not completed:
                                print("[!] Interrupted by user (barge-in active).")
                        else:
                            # Report fine-grained diagnostic category A-F
                            outcome = listen_res.outcome.value
                            err_detail = listen_res.error_message or "none"
                            d = listen_res.diagnostics
                            print(f"[{outcome}] chunks={d.chunks_received}, dur={d.window_seconds:.1f}s, peak_rms={d.peak_rms:.1f}, reason={err_detail}")
                            print("(Returning to standby.)\n")
                    finally:
                        # Invariant: Assistant must return to IDLE before the next wake-word / listening cycle
                        if state_machine.current_state != BuddyState.IDLE:
                            _recover_state_to_idle(state_machine, "Turn finalized")

            except asyncio.CancelledError:
                break
            except (KeyboardInterrupt, SystemExit):
                print("\nShutting down voice assistant...")
                break
            except Exception as err:
                print(f"Encountered error: {err}")
                await asyncio.sleep(0.5)
    finally:
        await capture.close()


def main() -> None:
    try:
        asyncio.run(run_voice_assistant())
    except KeyboardInterrupt:
        print("\nSession ended by user.")


if __name__ == "__main__":
    main()
