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
from app.voice.command_router import (
    VoiceCommandRouter,
    VoiceIntent,
    VoiceIntentType,
)
from app.voice.device import AudioDeviceManager
from app.voice.events import (
    SpeechStartedEvent,
    SpeechStoppedEvent,
    SpeechSynthesisFailedEvent,
    VoiceBargeInDetectedEvent,
    VoiceCommandReceivedEvent,
    VoiceLatencyRecordedEvent,
    VoiceListeningStartedEvent,
    VoiceListeningStoppedEvent,
    VoicePartialTranscriptEvent,
    VoiceRecognitionFailedEvent,
    VoiceSpeechDetectedEvent,
    VoiceSpeechEndedEvent,
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
    VoiceLatencyMetrics,
    VoiceOutcome,
)
from app.voice.pipeline import VoicePipeline
from app.voice.stt import (
    BatchFallbackStreamingSession,
    MockSTTProvider,
    MockStreamingSTTProvider,
    SpeechRecognitionSTTProvider,
    SpeechToTextProvider,
    StreamingSTTProvider,
    StreamingSTTSession,
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
    LocalWakeWordDetector,
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
    "VoiceLatencyMetrics",
    # Events
    "VoiceListeningStartedEvent",
    "VoiceListeningStoppedEvent",
    "VoiceCommandReceivedEvent",
    "VoiceRecognitionFailedEvent",
    "SpeechStartedEvent",
    "SpeechStoppedEvent",
    "SpeechSynthesisFailedEvent",
    "WakeWordDetectedEvent",
    "VoiceBargeInDetectedEvent",
    "VoicePartialTranscriptEvent",
    "VoiceSpeechDetectedEvent",
    "VoiceSpeechEndedEvent",
    "VoiceLatencyRecordedEvent",
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
    "StreamingSTTProvider",
    "StreamingSTTSession",
    "BatchFallbackStreamingSession",
    "MockSTTProvider",
    "MockStreamingSTTProvider",
    "SpeechRecognitionSTTProvider",
    # TTS
    "TextToSpeechProvider",
    "MockTTSProvider",
    "Pyttsx3TTSProvider",
    # Wake Word
    "WakeWordDetector",
    "MockWakeWordDetector",
    "KeywordWakeWordDetector",
    "LocalWakeWordDetector",
    # Pipeline
    "VoicePipeline",
    # Command Router
    "VoiceCommandRouter",
    "VoiceIntent",
    "VoiceIntentType",
]
