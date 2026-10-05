"""BUDDY Voice Activity Detection (VAD) Subsystem.

Provides speech boundary detection, energy-based utterance segmentation,
silence threshold timing, and mock VAD for unit testing.
"""

from __future__ import annotations

import logging
import math
import struct
import time
from abc import ABC, abstractmethod
from typing import Optional

from app.voice.models import AudioData, VADState

logger = logging.getLogger("buddy.voice.vad")


class VoiceActivityDetectorInterface(ABC):
    """Abstract interface defining Voice Activity Detection behaviors."""

    @abstractmethod
    def reset(self) -> None:
        """Reset the detector state for a new capture session."""

    @abstractmethod
    def process_chunk(self, chunk: bytes) -> VADState:
        """Process an incoming PCM chunk and return the current detection state."""

    @property
    @abstractmethod
    def state(self) -> VADState:
        """Current state of voice activity."""


class EnergyVAD(VoiceActivityDetectorInterface):
    """Energy-based voice activity detector using pure-Python RMS calculation.

    Detects transition: WAITING -> SPEAKING -> SILENCE -> COMPLETED.
    """

    def __init__(
        self,
        energy_threshold: float = 60.0,
        silence_timeout: float = 1.5,
        min_speech_duration: float = 0.3,
        max_recording_duration: float = 15.0,
        sample_rate: int = 16000,
        sample_width: int = 2,
    ) -> None:
        self.energy_threshold = energy_threshold
        self.silence_timeout = silence_timeout
        self.min_speech_duration = min_speech_duration
        self.max_recording_duration = max_recording_duration
        self.sample_rate = sample_rate
        self.sample_width = sample_width

        self._state: VADState = VADState.WAITING
        self._speech_started_time: Optional[float] = None
        self._silence_started_time: Optional[float] = None
        self._session_start_time: float = time.time()
        self._total_speech_bytes: int = 0

    def calibrate_ambient(self, ambient_rms: float) -> None:
        """Dynamically adjust energy threshold above the measured ambient room noise."""
        self.energy_threshold = max(35.0, ambient_rms * 2.2)
        logger.info("VAD: Calibrated to ambient RMS %.1f -> energy threshold: %.1f", ambient_rms, self.energy_threshold)

    @property
    def state(self) -> VADState:
        return self._state

    def reset(self) -> None:
        self._state = VADState.WAITING
        self._speech_started_time = None
        self._silence_started_time = None
        self._session_start_time = time.time()
        self._total_speech_bytes = 0

    @staticmethod
    def calculate_chunk_rms(chunk: bytes) -> float:
        """Calculate RMS amplitude of 16-bit PCM chunk without third-party dependencies."""
        if not chunk:
            return 0.0
        count = len(chunk) // 2
        if count == 0:
            return 0.0
        try:
            samples = struct.unpack(f"<{count}h", chunk[: count * 2])
            sum_squares = sum(s * s for s in samples)
            return math.sqrt(sum_squares / count)
        except Exception:
            return 0.0

    def process_chunk(self, chunk: bytes) -> VADState:
        now = time.time()
        rms = self.calculate_chunk_rms(chunk)
        is_speech = rms >= self.energy_threshold

        # Enforce maximum recording duration safety boundary
        if now - self._session_start_time >= self.max_recording_duration:
            logger.info("VAD: Maximum recording duration reached (%.1fs). Forcing COMPLETED.", self.max_recording_duration)
            self._state = VADState.COMPLETED
            return self._state

        if self._state == VADState.WAITING:
            if is_speech:
                self._state = VADState.SPEAKING
                self._speech_started_time = now
                self._silence_started_time = None
                self._total_speech_bytes += len(chunk)
                logger.debug("VAD: Speech onset detected (RMS=%.1f)", rms)

        elif self._state == VADState.SPEAKING:
            if is_speech:
                self._silence_started_time = None
                self._total_speech_bytes += len(chunk)
            else:
                self._state = VADState.SILENCE
                self._silence_started_time = now
                logger.debug("VAD: Transitioned SPEAKING -> SILENCE (RMS=%.1f)", rms)

        elif self._state == VADState.SILENCE:
            if is_speech:
                # User resumed speaking before silence timeout expired
                self._state = VADState.SPEAKING
                self._silence_started_time = None
                self._total_speech_bytes += len(chunk)
                logger.debug("VAD: Speech resumed from SILENCE (RMS=%.1f)", rms)
            else:
                elapsed_silence = now - (self._silence_started_time or now)
                speech_duration = (
                    (self._silence_started_time - (self._speech_started_time or now))
                    if self._speech_started_time
                    else 0.0
                )

                if elapsed_silence >= self.silence_timeout:
                    if speech_duration >= self.min_speech_duration:
                        self._state = VADState.COMPLETED
                        logger.info(
                            "VAD: Utterance completed (speech=%.2fs, silence=%.2fs)",
                            speech_duration,
                            elapsed_silence,
                        )
                    else:
                        # Noise spike was shorter than min_speech_duration; discard and wait
                        logger.debug("VAD: Noise transient ignored (duration=%.2fs). Resetting to WAITING.", speech_duration)
                        self.reset()

        return self._state


class MockVAD(VoiceActivityDetectorInterface):
    """Deterministic mock VAD for unit testing without audio signal processing."""

    def __init__(self, predefined_transitions: Optional[list[VADState]] = None) -> None:
        self._predefined = list(predefined_transitions or [])
        self._index = 0
        self._state: VADState = VADState.WAITING

    @property
    def state(self) -> VADState:
        return self._state

    def reset(self) -> None:
        self._index = 0
        self._state = VADState.WAITING

    def set_state(self, state: VADState) -> None:
        """Explicitly inject a state for test scenarios."""
        self._state = state

    def process_chunk(self, chunk: bytes) -> VADState:
        if self._index < len(self._predefined):
            self._state = self._predefined[self._index]
            self._index += 1
        return self._state
