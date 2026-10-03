"""BUDDY Voice Data Models.

Defines representations for audio buffers, audio devices, STT results,
and voice activity detection states.
"""

from __future__ import annotations

import io
import math
import struct
import time
import wave
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class VADState(str, Enum):
    """Voice activity detection states."""

    WAITING = "WAITING"
    SPEAKING = "SPEAKING"
    SILENCE = "SILENCE"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True)
class AudioDevice:
    """Represents a physical or virtual audio endpoint."""

    device_id: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: float
    is_input: bool
    is_output: bool
    hostapi_name: Optional[str] = None


@dataclass(frozen=True)
class AudioData:
    """Immutable audio buffer containing raw PCM data and format specifications."""

    raw_data: bytes
    sample_rate: int = 16000
    sample_width: int = 2  # 2 bytes = 16-bit PCM
    channels: int = 1

    @property
    def duration(self) -> float:
        """Calculate duration of audio in seconds."""
        bytes_per_second = self.sample_rate * self.channels * self.sample_width
        if bytes_per_second <= 0:
            return 0.0
        return len(self.raw_data) / bytes_per_second

    def to_wav_bytes(self) -> bytes:
        """Serialize raw PCM data to a complete RIFF/WAV byte stream."""
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(self.channels)
            wav_file.setsampwidth(self.sample_width)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(self.raw_data)
        return buffer.getvalue()

    def to_pcm_bytes(self) -> bytes:
        """Return raw PCM byte buffer."""
        return self.raw_data

    def calculate_rms_energy(self) -> float:
        """Calculate root-mean-square (RMS) energy in pure Python without audioop."""
        if not self.raw_data:
            return 0.0

        count = len(self.raw_data) // 2
        if count == 0:
            return 0.0

        # Unpack 16-bit signed little-endian integers
        format_str = f"<{count}h"
        try:
            samples = struct.unpack(format_str, self.raw_data[: count * 2])
            sum_squares = sum(s * s for s in samples)
            rms = math.sqrt(sum_squares / count)
            return float(rms)
        except Exception:
            return 0.0


@dataclass(frozen=True)
class STTResult:
    """Structured transcription result returned by speech-to-text providers."""

    transcript: str
    confidence: Optional[float] = None
    language: Optional[str] = "en"
    duration: float = 0.0
    provider: str = "mock"
    timestamp: float = field(default_factory=time.time)
