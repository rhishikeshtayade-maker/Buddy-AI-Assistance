"""BUDDY Voice Pipeline Events.

Defines typed events for microphone listening, transcription receipt,
speech synthesis lifecycle, and voice subsystem diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.core.events import BaseEvent


@dataclass(frozen=True)
class VoiceListeningStartedEvent(BaseEvent):
    """Emitted when the voice pipeline activates microphone capture and VAD."""

    input_device: str = "default"
    sample_rate: int = 16000


@dataclass(frozen=True)
class VoiceListeningStoppedEvent(BaseEvent):
    """Emitted when the voice pipeline ceases microphone capture."""

    reason: str = "Capture finished"
    duration: float = 0.0


@dataclass(frozen=True)
class VoiceCommandReceivedEvent(BaseEvent):
    """Emitted when speech has been captured and transcribed into a voice command."""

    transcript: str = ""
    confidence: Optional[float] = None
    duration: float = 0.0
    provider: str = "mock"


@dataclass(frozen=True)
class VoiceRecognitionFailedEvent(BaseEvent):
    """Emitted when speech recognition fails, times out, or detects empty speech."""

    error_type: str = "RecognitionFailure"
    message: str = "Speech recognition failed"
    details: Optional[dict] = None


@dataclass(frozen=True)
class SpeechStartedEvent(BaseEvent):
    """Emitted when Text-to-Speech starts synthesizing or voicing audio."""

    text: str = ""
    voice: Optional[str] = None


@dataclass(frozen=True)
class SpeechStoppedEvent(BaseEvent):
    """Emitted when Text-to-Speech finishes voicing audio or is interrupted."""

    text: str = ""
    completed: bool = True
    interrupted: bool = False


@dataclass(frozen=True)
class SpeechSynthesisFailedEvent(BaseEvent):
    """Emitted when Text-to-Speech synthesis encounters an unhandled failure."""

    text: str = ""
    error_type: str = "SynthesisError"
    message: str = "Speech synthesis failed"


@dataclass(frozen=True)
class WakeWordDetectedEvent(BaseEvent):
    """Emitted when wake word activation phrase is recognized in audio."""

    wake_word: str = "hey buddy"
    confidence: float = 1.0


@dataclass(frozen=True)
class VoiceBargeInDetectedEvent(BaseEvent):
    """Emitted when user voice interruption (barge-in) cancels active speech playback."""

    reason: str = "User speech detected during playback"
    rms_energy: float = 0.0


@dataclass(frozen=True)
class VoicePartialTranscriptEvent(BaseEvent):
    """Emitted when streaming STT delivers an intermediate partial transcript."""

    partial_text: str = ""
    is_final: bool = False


@dataclass(frozen=True)
class VoiceSpeechDetectedEvent(BaseEvent):
    """Emitted when VAD detects speech onset."""

    rms: float = 0.0
    threshold: float = 0.0


@dataclass(frozen=True)
class VoiceSpeechEndedEvent(BaseEvent):
    """Emitted when VAD detects utterance completion."""

    speech_seconds: float = 0.0
    reason: str = "silence_timeout"


@dataclass(frozen=True)
class VoiceLatencyRecordedEvent(BaseEvent):
    """Emitted when turn completes with numeric latency metadata."""

    total_turn_ms: float = 0.0
    metrics_summary: Optional[dict] = None

