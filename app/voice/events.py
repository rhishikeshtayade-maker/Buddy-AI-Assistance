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
