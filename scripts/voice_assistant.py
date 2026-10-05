"""BUDDY Live Interactive Voice Assistant.

Run directly via:
    python scripts/voice_assistant.py

Features:
- Live voice activation via wake word ("Hey BUDDY") or pressing [ENTER].
- Real-time microphone capture & Google Speech-to-Text transcription.
- Conversational turn execution with tool actions.
- Text-to-Speech audio response playback via Windows pyttsx3.
"""

import asyncio
import os
import sys
from pathlib import Path

# Ensure project root in sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from app.ai.conversation import ConversationManager
from app.core import BuddyConfig, BuddyState, EventBus, StateMachine
from app.tools.builtin import register_builtin_tools
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.voice.capture import SoundDeviceAudioCapture
from app.voice.device import AudioDeviceManager
from app.voice.pipeline import VoicePipeline
from app.voice.stt import SpeechRecognitionSTTProvider
from app.voice.tts import Pyttsx3TTSProvider
from app.voice.vad import EnergyVAD
from app.voice.wake import KeywordWakeWordDetector


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

    # 2. Initialize Tool Subsystem & Conversation Manager
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

    # 3. Welcome Announcement
    welcome_text = "BUDDY voice assistant is online. How can I help you?"
    print(f"\nBUDDY: {welcome_text}")
    try:
        await pipeline.speak(welcome_text)
    except Exception as e:
        print(f"(Audio playback notice: {e})")

    print("\nHow to interact:")
    print("  - Speak the wake word: 'Hey BUDDY', then say your command")
    print("  - Or press [ENTER] at any time to talk directly")
    print("  - Say 'goodbye' or 'exit' (or press Ctrl+C) to terminate\n")

    loop = asyncio.get_running_loop()

    while True:
        try:
            print("Listening for wake word ('Hey BUDDY') or press [ENTER] to speak...")

            # Wait for either wake word detection or keyboard press
            listen_task = asyncio.create_task(pipeline.listen_for_wake_word(timeout=8.0))
            input_task = asyncio.create_task(loop.run_in_executor(None, sys.stdin.readline))

            done, pending = await asyncio.wait(
                [listen_task, input_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            for t in pending:
                t.cancel()

            activated = False
            if listen_task in done and listen_task.result():
                print("\n[!] Wake word detected!")
                activated = True
            elif input_task in done:
                print("\n[!] Activated by user keypress.")
                activated = True

            if activated:
                # Audible prompt
                try:
                    await pipeline.speak("I'm listening.")
                except Exception:
                    pass

                print(">>> LISTENING FOR YOUR COMMAND (speak now)... <<<")
                stt_result = await pipeline.listen_for_command(timeout=7.0)

                if stt_result and stt_result.transcript:
                    user_cmd = stt_result.transcript.strip()
                    print(f"\nYou said: \"{user_cmd}\"")

                    # Check exit commands
                    if user_cmd.lower() in ("exit", "quit", "goodbye", "bye", "shutdown"):
                        farewell = "Goodbye! Have a great day."
                        print(f"BUDDY: {farewell}")
                        await pipeline.speak(farewell)
                        break

                    # Process conversational turn with AI and tools
                    response = await conv_manager.process_user_turn(user_cmd, voice_response=True)
                    print(f"BUDDY: {response.content}\n")
                else:
                    print("(No speech recognized. Returning to standby.)\n")

        except asyncio.CancelledError:
            break
        except (KeyboardInterrupt, SystemExit):
            print("\nShutting down voice assistant...")
            break
        except Exception as err:
            print(f"Encountered error: {err}")
            await asyncio.sleep(1.0)


def main() -> None:
    try:
        asyncio.run(run_voice_assistant())
    except KeyboardInterrupt:
        print("\nSession ended by user.")


if __name__ == "__main__":
    main()
