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

# Ensure project root in sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.ai.conversation import ConversationManager
from app.core import BuddyConfig, BuddyState, EventBus, StateMachine
from app.tools.builtin import register_builtin_tools
from app.tools.executor import ToolExecutor
from app.tools.models import ToolRequest
from app.tools.registry import ToolRegistry
from app.voice.capture import SoundDeviceAudioCapture
from app.voice.device import AudioDeviceManager
from app.voice.pipeline import VoicePipeline
from app.voice.stt import SpeechRecognitionSTTProvider
from app.voice.tts import Pyttsx3TTSProvider
from app.voice.vad import EnergyVAD
from app.voice.wake import KeywordWakeWordDetector


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


async def execute_direct_command(user_cmd: str, tool_executor: ToolExecutor) -> tuple[bool, str]:
    """Execute common voice commands directly through tools for instant responsiveness."""
    cmd_lower = user_cmd.lower().strip()

    # Time command
    if any(q in cmd_lower for q in ["what time is it", "current time", "tell me the time", "what's the time"]):
        now_str = datetime.datetime.now().strftime("%I:%M %p")
        return True, f"The current time is {now_str}."

    # Date command
    if any(q in cmd_lower for q in ["what's today's date", "what is today's date", "what date is it", "today's date"]):
        today_str = datetime.datetime.now().strftime("%A, %B %d, %Y")
        return True, f"Today is {today_str}."

    # Battery command
    if any(q in cmd_lower for q in ["battery", "battery level", "power remaining"]):
        req = ToolRequest(tool_name="system.get_battery", arguments={})
        res = await tool_executor.execute(req)
        if res.success and isinstance(res.output, dict):
            percent = res.output.get("percent", "unknown")
            plugged = res.output.get("power_plugged", False)
            status = "plugged in" if plugged else "running on battery"
            return True, f"Your battery is at {percent}% and is currently {status}."
        return True, "Unable to query battery status."

    # Volume command
    if "volume" in cmd_lower:
        req = ToolRequest(tool_name="system.get_volume", arguments={})
        res = await tool_executor.execute(req)
        if res.success and isinstance(res.output, dict):
            vol = res.output.get("volume", "unknown")
            return True, f"The current system volume is at {vol}%."

    # App launch: Notepad
    if "open notepad" in cmd_lower or "launch notepad" in cmd_lower:
        req = ToolRequest(tool_name="app.open", arguments={"application": "notepad"})
        res = await tool_executor.execute(req)
        if res.success:
            return True, "Opening Notepad."
        return True, "Failed to launch Notepad."

    # App launch: Calculator
    if "open calculator" in cmd_lower or "launch calculator" in cmd_lower or "open calc" in cmd_lower:
        req = ToolRequest(tool_name="app.open", arguments={"application": "calc"})
        res = await tool_executor.execute(req)
        if res.success:
            return True, "Opening Calculator."
        return True, "Failed to launch Calculator."

    return False, ""


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

    # 1. Initialize Hardware Voice Pipeline
    capture = SoundDeviceAudioCapture(
        sample_rate=config.audio_sample_rate,
        channels=config.audio_channels,
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

    # 3. Initialize Tool Subsystem & Conversation Manager
    registry = ToolRegistry()
    register_builtin_tools(registry)
    tool_executor = ToolExecutor(registry=registry, event_bus=event_bus)

    conv_manager = ConversationManager(
        config=config,
        event_bus=event_bus,
        state_machine=state_machine,
        voice_pipeline=pipeline,
        tool_executor=tool_executor,
    )

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
                    # Audible prompt
                    try:
                        await pipeline.speak("I'm listening.")
                    except Exception:
                        pass

                    print(">>> LISTENING FOR YOUR COMMAND (speak now)... <<<")
                    listen_res = await pipeline.listen_with_diagnostics(timeout=7.0)

                    if listen_res.ok and listen_res.transcript:
                        user_cmd = listen_res.transcript.strip()
                        print(f"\nYou said: \"{user_cmd}\" (latency: capture={listen_res.capture_latency:.2f}s, stt={listen_res.stt_latency:.2f}s)")

                        # Check exit commands
                        if user_cmd.lower() in ("exit", "quit", "goodbye", "bye", "shutdown"):
                            farewell = "Goodbye! Have a great day."
                            print(f"BUDDY: {farewell}")
                            await pipeline.speak(farewell)
                            break

                        # Check direct tool / system actions first
                        handled, direct_response = await execute_direct_command(user_cmd, tool_executor)
                        if handled:
                            print(f"BUDDY: {direct_response}\n")
                            await pipeline.speak(direct_response)
                        else:
                            # Conversational AI turn
                            response = await conv_manager.process_user_turn(user_cmd, voice_response=True)
                            print(f"BUDDY: {response.content}\n")
                    else:
                        # Report fine-grained diagnostic category A-F
                        outcome = listen_res.outcome.value
                        err_detail = listen_res.error_message or "none"
                        d = listen_res.diagnostics
                        print(f"[{outcome}] chunks={d.chunks_received}, dur={d.window_seconds:.1f}s, peak_rms={d.peak_rms:.1f}, reason={err_detail}")
                        print("(Returning to standby.)\n")

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
