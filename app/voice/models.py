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
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


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


# ---------------------------------------------------------------------------
# Loop 13: Explicit live-voice outcome taxonomy & diagnostics
# ---------------------------------------------------------------------------


class TranscriptionStatus(str, Enum):
    """Fine-grained status of a single listen/transcribe attempt."""

    LISTENING = "LISTENING"
    SPEECH_DETECTED = "SPEECH_DETECTED"
    TRANSCRIBING = "TRANSCRIBING"
    TRANSCRIPTION_SUCCESS = "TRANSCRIPTION_SUCCESS"
    TRANSCRIPTION_EMPTY = "TRANSCRIPTION_EMPTY"
    TRANSCRIPTION_UNCLEAR = "TRANSCRIPTION_UNCLEAR"
    TRANSCRIPTION_ERROR = "TRANSCRIPTION_ERROR"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


class VoiceOutcome(str, Enum):
    """End-to-end voice turn outcome. Each failure mode is distinct by design.

    A  MIC_UNAVAILABLE      - microphone could not be opened
    B  NO_FRAMES            - stream opened but no audio frames arrived
    C  SILENCE              - frames arrived but no speech was detected
    D  STT_FAILED           - speech detected but transcription failed
    E  ROUTING_FAILED       - transcript obtained but command processing failed
    F  VERIFICATION_FAILED  - action executed but could not be verified / was blocked
    G  SUCCESS              - everything succeeded
    """

    MIC_UNAVAILABLE = "MIC_UNAVAILABLE"
    NO_FRAMES = "NO_FRAMES"
    SILENCE = "SILENCE"
    STT_FAILED = "STT_FAILED"
    ROUTING_FAILED = "ROUTING_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    ACTION_BLOCKED = "ACTION_BLOCKED"
    SUCCESS = "SUCCESS"
    CANCELLED = "CANCELLED"
    # Intermediate: listening layer succeeded and produced a transcript.
    TRANSCRIBED = "TRANSCRIBED"


@dataclass
class CaptureDiagnostics:
    """Privacy-safe numeric diagnostics of one bounded capture window.

    Contains NO audio samples and NO transcript text.
    """

    stream_opened: bool = False
    chunks_received: int = 0
    bytes_received: int = 0
    window_seconds: float = 0.0
    first_chunk_latency: Optional[float] = None
    peak_rms: float = 0.0
    mean_rms: float = 0.0
    noise_floor: float = 0.0
    energy_threshold: float = 0.0
    speech_detected: bool = False
    speech_seconds: float = 0.0
    utterance_seconds: float = 0.0
    termination: str = "unknown"
    error: Optional[str] = None



class VoiceLatencyMetrics(BaseModel):
    """Fine-grained monotonic latency metrics for an end-to-end voice turn (all in milliseconds).

    Strict privacy & security invariant:
      Contains ONLY numeric timing measurements and safe structural metadata.
      Never contains raw audio samples, transcripts, API keys, passwords, or secrets.
    """

    wake_detection_ms: Optional[float] = None
    capture_start_ms: Optional[float] = None
    capture_end_ms: Optional[float] = None
    stt_start_ms: Optional[float] = None
    first_transcript_ms: Optional[float] = None
    stt_complete_ms: Optional[float] = None
    routing_start_ms: Optional[float] = None
    routing_complete_ms: Optional[float] = None
    tool_start_ms: Optional[float] = None
    tool_complete_ms: Optional[float] = None
    ai_start_ms: Optional[float] = None
    first_ai_token_ms: Optional[float] = None
    ai_complete_ms: Optional[float] = None
    tts_start_ms: Optional[float] = None
    first_audio_output_ms: Optional[float] = None
    tts_complete_ms: Optional[float] = None
    barge_in_latency_ms: Optional[float] = None
    total_turn_ms: Optional[float] = None

    # Safe metadata
    intent_type: Optional[str] = None
    stt_provider: Optional[str] = None
    ai_provider: Optional[str] = None
    tts_provider: Optional[str] = None
    barge_in_triggered: bool = False
    success: bool = True

    model_config = {
        "extra": "forbid",
    }

    def to_safe_dict(self) -> Dict[str, Any]:
        """Return metadata and numeric timings dict guaranteed free of sensitive content."""
        return {k: v for k, v in self.model_dump().items() if v is not None}


@dataclass
class ListenResult:
    """Result of a categorized listen attempt (capture -> VAD -> STT)."""

    outcome: VoiceOutcome
    transcription_status: TranscriptionStatus = TranscriptionStatus.NOT_ATTEMPTED
    stt_result: Optional[STTResult] = None
    diagnostics: CaptureDiagnostics = field(default_factory=CaptureDiagnostics)
    latency_metrics: Optional[VoiceLatencyMetrics] = None
    error_message: Optional[str] = None
    capture_latency: float = 0.0
    stt_latency: float = 0.0
    total_latency: float = 0.0

    @property
    def transcript(self) -> str:
        return self.stt_result.transcript if self.stt_result else ""

    @property
    def ok(self) -> bool:
        return self.outcome == VoiceOutcome.TRANSCRIBED and bool(self.transcript.strip())

