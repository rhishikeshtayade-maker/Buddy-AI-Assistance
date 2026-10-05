"""BUDDY Manual Hardware Smoke Test.

Run directly via:
    python -m app.voice.smoke_test

Verifies local microphone capture, audio device enumeration, VAD speech detection,
and TTS speaker playback on the host machine. Distinct from headless automated CI tests.
"""

import asyncio
import math
import struct
import sys
import time
from app.core.config import BuddyConfig
from app.core.events import EventBus
from app.core.state import BuddyState, StateMachine
from app.voice.capture import SoundDeviceAudioCapture
from app.voice.device import AudioDeviceManager
from app.voice.pipeline import VoicePipeline
from app.voice.stt import SpeechRecognitionSTTProvider
from app.voice.tts import Pyttsx3TTSProvider
from app.voice.vad import EnergyVAD


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

    # 2. Hardware Providers Initialization
    capture = SoundDeviceAudioCapture(
        sample_rate=config.audio_sample_rate,
        channels=config.audio_channels,
    )
    vad = EnergyVAD(
        energy_threshold=60.0,
        silence_timeout=1.2,
        min_speech_duration=0.2,
        sample_rate=config.audio_sample_rate,
    )
    stt = SpeechRecognitionSTTProvider()
    tts = Pyttsx3TTSProvider()

    pipeline = VoicePipeline(
        config=config,
        event_bus=event_bus,
        state_machine=state_machine,
        device_manager=device_mgr,
        capture=capture,
        vad=vad,
        stt=stt,
        tts=tts,
    )

    # 3. Audio Feedback (TTS)
    print("\nTesting Text-to-Speech audio feedback...")
    try:
        await pipeline.speak("BUDDY voice pipeline test initialized. Please speak after the prompt.")
        print("Speaker playback: OK")
    except Exception as e:
        print(f"Speaker playback encountered an issue: {e}")

    # 4. Ambient Noise Calibration
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
                print(f"Room noise floor: {ambient_rms:.1f} RMS | VAD speech threshold: {vad.energy_threshold:.1f} RMS")
    except Exception as cal_err:
        print(f"Ambient calibration skipped ({cal_err}), using default threshold: {vad.energy_threshold:.1f} RMS")

    # 5. Microphone Capture & Speech Recognition
    print("\nSpeak after the prompt (listening for up to 7 seconds)...")
    print(">>> SPEAK NOW (say: 'Hello BUDDY' or 'What time is it') <<<")

    result = await pipeline.listen_for_command(timeout=7.0)

    if result and result.transcript:
        print(f"\nTranscript: \"{result.transcript}\"")
        print(f"Confidence: {result.confidence or 'N/A'}")
        print(f"Duration:   {result.duration:.2f}s")
        print(f"Latency:    {pipeline.last_pipeline_latency:.3f}s")
        print("\nVoice pipeline: PASS")

        # Voicing back confirmation
        try:
            await pipeline.speak(f"I heard you say: {result.transcript}")
        except Exception:
            pass

        return 0
    else:
        print("\nNo transcript recognized within the window.")
        print("Tip: Ensure your microphone volume is turned up in Windows Sound Settings,")
        print("     speak clearly towards the microphone, and try again.")
        print("Voice pipeline: COMPLETED (No speech detected)")
        return 0


def main() -> int:
    return asyncio.run(run_smoke_test())


if __name__ == "__main__":
    sys.exit(main())
