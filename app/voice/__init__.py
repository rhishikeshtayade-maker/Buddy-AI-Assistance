"""BUDDY Voice Pipeline Subsystem.

Provides microphone audio capture, voice activity detection (VAD),
speech-to-text (STT), text-to-speech (TTS), wake word detection,
and decoupled voice events.
"""

from app.voice.capture import (
    AudioCaptureInterface,
    MockAudioCapture,
    SoundDeviceAudioCapture,
)
from app.voice.device import AudioDeviceManager
from app.voice.events import (
    SpeechStartedEvent,
    SpeechStoppedEvent,
    SpeechSynthesisFailedEvent,
    VoiceCommandReceivedEvent,
    VoiceListeningStartedEvent,
    VoiceListeningStoppedEvent,
    VoiceRecognitionFailedEvent,
    WakeWordDetectedEvent,
)
from app.voice.exceptions import (
    AudioCaptureError,
    AudioDeviceError,
    NoAudioFramesError,
    STTEmptyError,
    STTError,
    STTServiceError,
    STTTimeoutError,
    STTUnclearError,
    TTSError,
    VADError,
    VoiceError,
    WakeWordError,
)
from app.voice.models import (
    AudioData,
    AudioDevice,
    CaptureDiagnostics,
    ListenResult,
    STTResult,
    TranscriptionStatus,
    VADState,
    VoiceOutcome,
)
from app.voice.pipeline import VoicePipeline
from app.voice.stt import (
    MockSTTProvider,
    SpeechRecognitionSTTProvider,
    SpeechToTextProvider,
)
from app.voice.tts import (
    MockTTSProvider,
    Pyttsx3TTSProvider,
    TextToSpeechProvider,
)
from app.voice.vad import (
    EnergyVAD,
    MockVAD,
    VoiceActivityDetectorInterface,
)
from app.voice.wake import (
    KeywordWakeWordDetector,
    MockWakeWordDetector,
    WakeWordDetector,
)

__all__ = [
    # Models
    "AudioData",
    "AudioDevice",
    "STTResult",
    "VADState",
    "TranscriptionStatus",
    "VoiceOutcome",
    "CaptureDiagnostics",
    "ListenResult",
    # Events
    "VoiceListeningStartedEvent",
    "VoiceListeningStoppedEvent",
    "VoiceCommandReceivedEvent",
    "VoiceRecognitionFailedEvent",
    "SpeechStartedEvent",
    "SpeechStoppedEvent",
    "SpeechSynthesisFailedEvent",
    "WakeWordDetectedEvent",
    # Exceptions
    "VoiceError",
    "AudioDeviceError",
    "AudioCaptureError",
    "NoAudioFramesError",
    "VADError",
    "STTError",
    "STTEmptyError",
    "STTUnclearError",
    "STTServiceError",
    "STTTimeoutError",
    "TTSError",
    "WakeWordError",
    # Device
    "AudioDeviceManager",
    # Capture
    "AudioCaptureInterface",
    "MockAudioCapture",
    "SoundDeviceAudioCapture",
    # VAD
    "VoiceActivityDetectorInterface",
    "EnergyVAD",
    "MockVAD",
    # STT
    "SpeechToTextProvider",
    "MockSTTProvider",
    "SpeechRecognitionSTTProvider",
    # TTS
    "TextToSpeechProvider",
    "MockTTSProvider",
    "Pyttsx3TTSProvider",
    # Wake Word
    "WakeWordDetector",
    "MockWakeWordDetector",
    "KeywordWakeWordDetector",
    # Pipeline
    "VoicePipeline",
]
