"""BUDDY Voice Pipeline Exception Hierarchy.

Defines typed exceptions for audio devices, capture, voice activity detection,
speech-to-text, text-to-speech, and wake word recognition errors.
"""

from typing import Optional
from app.core.exceptions import BuddyError


class VoiceError(BuddyError):
    """Base exception for all voice subsystem failures."""


class AudioDeviceError(VoiceError):
    """Raised when an audio input or output device is missing, disconnected, or invalid."""

    def __init__(self, message: str, device_name: Optional[str] = None, details: Optional[dict] = None) -> None:
        d = details or {}
        if device_name:
            d["device_name"] = device_name
        super().__init__(message, details=d)
        self.device_name = device_name


class AudioCaptureError(VoiceError):
    """Raised when audio capture initialization or streaming fails."""


class VADError(VoiceError):
    """Raised when Voice Activity Detection encounters invalid input or timing errors."""


class STTError(VoiceError):
    """Raised when Speech-to-Text transcription fails or times out."""


class TTSError(VoiceError):
    """Raised when Text-to-Speech synthesis or audio playback fails."""


class WakeWordError(VoiceError):
    """Raised when wake word detection fails or encounters internal errors."""
