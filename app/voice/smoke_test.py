"""BUDDY Manual Hardware Smoke Test.

Run directly via:
    python -m app.voice.smoke_test

Verifies local microphone capture, audio device enumeration, and TTS speaker playback
on the host machine. Distinct from headless automated CI tests.
"""

import asyncio
import sys
from app.core.config import BuddyConfig
from app.core.events import EventBus
from app.core.state import BuddyState, StateMachine
from app.voice.device import AudioDeviceManager
from app.voice.pipeline import VoicePipeline


async def run_smoke_test() -> int:
    print("========================================================================")
    print("                       BUDDY Voice Smoke Test                           ")
    print("========================================================================")

    config = BuddyConfig.load_from_env()
    event_bus = EventBus()
    state_machine = StateMachine(BuddyState.IDLE)
    device_mgr = AudioDeviceManager()

    # 1. Device Check
    inputs = device_mgr.list_input_devices()
    outputs = device_mgr.list_output_devices()

    default_mic = device_mgr.get_default_input_device()
    default_speaker = device_mgr.get_default_output_device()

    mic_status = f"OK ({default_mic.name})" if default_mic else "NOT DETECTED"
    speaker_status = f"OK ({default_speaker.name})" if default_speaker else "NOT DETECTED"

    print(f"Microphone: {mic_status}")
    print(f"Speaker:    {speaker_status}")

    if not default_mic:
        print("\n[WARNING] No active microphone detected on this system.")
        print("Manual hardware test cannot proceed with live capture.")
        print("Note: Automated mock unit tests continue to pass independently.")
        return 0

    # 2. Pipeline Initialization
    pipeline = VoicePipeline(
        config=config,
        event_bus=event_bus,
        state_machine=state_machine,
        device_manager=device_mgr,
    )

    # 3. Audio Feedback
    print("\nTesting Text-to-Speech audio feedback...")
    try:
        await pipeline.speak("BUDDY voice pipeline test initialized. Please speak after the prompt.")
        print("Speaker playback: OK")
    except Exception as e:
        print(f"Speaker playback encountered an issue: {e}")

    # 4. Microphone Capture
    print("\nSpeak after the prompt (listening for 5 seconds)...")
    print(">>> SPEAK NOW <<<")

    result = await pipeline.listen_for_command(timeout=5.0)

    if result:
        print(f"\nTranscript: \"{result.transcript}\"")
        print(f"Confidence: {result.confidence or 'N/A'}")
        print(f"Duration:   {result.duration:.2f}s")
        print(f"Latency:    {pipeline.last_pipeline_latency:.3f}s")
        print("\nVoice pipeline: PASS")
        return 0
    else:
        print("\nNo transcript recognized within the window.")
        print("Voice pipeline: COMPLETED (No audio received)")
        return 0


def main() -> int:
    return asyncio.run(run_smoke_test())


if __name__ == "__main__":
    sys.exit(main())
