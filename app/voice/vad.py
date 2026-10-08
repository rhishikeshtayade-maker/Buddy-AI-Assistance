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
from collections import deque
from typing import Deque, List, Optional

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

    @property
    def is_speech_started(self) -> bool:
        """Return True on the chunk when speech onset occurs."""
        return False

    @property
    def is_speech_active(self) -> bool:
        """Return True while speech utterance is active (SPEAKING or brief SILENCE)."""
        return self.state in (VADState.SPEAKING, VADState.SILENCE)

    @property
    def is_speech_ended(self) -> bool:
        """Return True when an utterance has ended and completed."""
        return self.state == VADState.COMPLETED

    def process_chunk_event(self, chunk: bytes) -> tuple[VADState, str]:
        """Process chunk and return (state, event_type)."""
        state = self.process_chunk(chunk)
        return state, getattr(self, "current_vad_event", "none")


class EnergyVAD(VoiceActivityDetectorInterface):
    """Adaptive energy-based voice activity detector using pure-Python RMS calculation.

    Detects transition: WAITING -> SPEAKING -> SILENCE -> COMPLETED.

    Loop 13 hardening:
      * Ambient calibration (``calibrate_ambient``) using a robust noise-floor estimate.
      * Dynamic threshold: after calibration, the noise floor tracks slow ambient drift
        using an EMA updated ONLY from non-speech frames while WAITING.
      * Hysteresis: speech continues at a lower threshold than onset, so soft
        word endings do not prematurely cut an utterance.
      * Minimum speech duration: short clicks / bumps are discarded as transients.
      * Silence termination after ``silence_timeout``.
      * Bounded duration: ``max_recording_duration`` measured from speech onset
        (or from session start while still waiting). The session start is NOT
        reset by transient rejection, so the bound always holds.
      * Noise-burst recovery: ``recover_from_noise`` re-estimates the floor from
        recent frames after a false trigger.
      * Optional audio clock (``use_audio_clock=True``) derives timing from the
        number of samples processed instead of wall time, making the detector
        immune to event-loop scheduling jitter and backlog bursts.
    """

    def __init__(
        self,
        energy_threshold: float = 60.0,
        silence_timeout: float = 1.5,
        min_speech_duration: float = 0.3,
        max_recording_duration: float = 15.0,
        sample_rate: int = 16000,
        sample_width: int = 2,
        *,
        min_threshold: float = 35.0,
        noise_ratio: float = 2.2,
        noise_margin: float = 40.0,
        continue_ratio: float = 0.75,
        adaptive: bool = True,
        noise_adapt_rate: float = 0.05,
        use_audio_clock: bool = False,
    ) -> None:
        self.energy_threshold = energy_threshold
        self.silence_timeout = silence_timeout
        self.min_speech_duration = min_speech_duration
        self.max_recording_duration = max_recording_duration
        self.sample_rate = sample_rate
        self.sample_width = sample_width

        self.min_threshold = min_threshold
        self.noise_ratio = noise_ratio
        self.noise_margin = noise_margin
        self.continue_ratio = continue_ratio
        self.adaptive = adaptive
        self.noise_adapt_rate = noise_adapt_rate
        self.use_audio_clock = use_audio_clock

        self.noise_floor: Optional[float] = None
        self._calibrated = False
        self._recent_rms: Deque[float] = deque(maxlen=64)

        self._state: VADState = VADState.WAITING
        self._speech_started_time: Optional[float] = None
        self._silence_started_time: Optional[float] = None
        self._session_start_time: float = 0.0
        self._audio_clock: float = 0.0
        self._total_speech_bytes: int = 0
        self._speech_confirmed = False
        self.completion_reason: Optional[str] = None
        self.last_rms: float = 0.0
        self.peak_rms: float = 0.0
        self.last_speech_seconds: float = 0.0
        self.current_vad_event: str = "none"
        self._speech_just_started: bool = False
        self.reset()

    # ------------------------------------------------------------------ calibration
    @property
    def is_calibrated(self) -> bool:
        return self._calibrated

    def _threshold_from_floor(self, floor: float) -> float:
        return max(self.min_threshold, floor * self.noise_ratio, floor + self.noise_margin)

    def calibrate_ambient(self, ambient_rms: float) -> None:
        """Dynamically adjust energy threshold above the measured ambient room noise."""
        floor = max(0.0, float(ambient_rms))
        self.noise_floor = floor
        self.energy_threshold = self._threshold_from_floor(floor)
        self._calibrated = True
        logger.info("VAD: Calibrated to ambient RMS %.1f -> energy threshold: %.1f", floor, self.energy_threshold)

    @staticmethod
    def estimate_noise_floor(chunk_rms_values: List[float]) -> float:
        """Robust noise floor: median of per-chunk RMS, ignoring device start-up zeros."""
        vals = sorted(v for v in chunk_rms_values if v > 1.0)
        if not vals:
            vals = sorted(chunk_rms_values)
        if not vals:
            return 0.0
        mid = len(vals) // 2
        if len(vals) % 2:
            return float(vals[mid])
        return float((vals[mid - 1] + vals[mid]) / 2.0)

    def recover_from_noise(self) -> bool:
        """Re-estimate the noise floor from recent frames after a false trigger.

        Uses the 30th percentile of recent per-chunk RMS so a residual burst does
        not dominate. Returns True if the threshold changed.
        """
        if len(self._recent_rms) < 8:
            return False
        vals = sorted(self._recent_rms)
        p30 = vals[int(len(vals) * 0.3)]
        new_threshold = self._threshold_from_floor(p30)
        if abs(new_threshold - self.energy_threshold) < 1.0:
            return False
        logger.info(
            "VAD: Noise recovery adjusted threshold %.1f -> %.1f (floor %.1f)",
            self.energy_threshold,
            new_threshold,
            p30,
        )
        self.noise_floor = p30
        self.energy_threshold = new_threshold
        self._calibrated = True
        return True

    def _adapt_noise_floor(self, rms: float) -> None:
        if not (self.adaptive and self._calibrated) or self.noise_floor is None:
            return
        a = self.noise_adapt_rate
        self.noise_floor = (1.0 - a) * self.noise_floor + a * rms
        self.energy_threshold = self._threshold_from_floor(self.noise_floor)

    # ------------------------------------------------------------------ state
    @property
    def state(self) -> VADState:
        return self._state

    @property
    def has_speech(self) -> bool:
        """True once an utterance of at least ``min_speech_duration`` has been observed."""
        return self._speech_confirmed

    def reset(self) -> None:
        self._audio_clock = 0.0
        self._session_start_time = self._clock_now()
        self._reset_utterance()
        self._speech_confirmed = False
        self.completion_reason = None
        self.peak_rms = 0.0
        self.last_rms = 0.0
        self.last_speech_seconds = 0.0
        self.current_vad_event = "none"
        self._speech_just_started = False

    @property
    def is_speech_started(self) -> bool:
        """True only on the exact chunk where speech onset occurred."""
        return self._speech_just_started

    @property
    def is_speech_active(self) -> bool:
        """True while speech is actively progressing."""
        return self._state in (VADState.SPEAKING, VADState.SILENCE)

    @property
    def is_speech_ended(self) -> bool:
        """True when utterance boundary has ended."""
        return self._state == VADState.COMPLETED and self._speech_confirmed

    def _reset_utterance(self) -> None:
        """Discard the current (transient) utterance without resetting session bounds."""
        self._state = VADState.WAITING
        self._speech_started_time = None
        self._silence_started_time = None
        self._total_speech_bytes = 0

    def _clock_now(self) -> float:
        return self._audio_clock if self.use_audio_clock else time.time()

    def _chunk_seconds(self, chunk: bytes) -> float:
        bps = self.sample_rate * self.sample_width
        return (len(chunk) / bps) if bps > 0 else 0.0

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
        self._speech_just_started = False
        self.current_vad_event = "none"

        if self._state == VADState.COMPLETED:
            return self._state

        if self.use_audio_clock:
            self._audio_clock += self._chunk_seconds(chunk)
        now = self._clock_now()

        rms = self.calculate_chunk_rms(chunk)
        self.last_rms = rms
        self.peak_rms = max(self.peak_rms, rms)
        self._recent_rms.append(rms)

        onset_threshold = self.energy_threshold
        continue_threshold = self.energy_threshold * self.continue_ratio
        in_utterance = self._state in (VADState.SPEAKING, VADState.SILENCE)
        is_speech = rms >= (continue_threshold if in_utterance else onset_threshold)

        # Enforce maximum duration safety boundary (from onset if speaking, else session start)
        bound_start = self._speech_started_time if self._speech_started_time is not None else self._session_start_time
        if now - bound_start >= self.max_recording_duration:
            if in_utterance:
                speech_dur = now - (self._speech_started_time or now)
                self.last_speech_seconds = speech_dur
                if speech_dur >= self.min_speech_duration:
                    self._speech_confirmed = True
            self.completion_reason = "max_duration" if in_utterance else "no_speech"
            self.current_vad_event = "speech_ended" if in_utterance else "no_speech"
            logger.info("VAD: Maximum recording duration reached (%.1fs). Forcing COMPLETED.", self.max_recording_duration)
            self._state = VADState.COMPLETED
            return self._state

        if self._state == VADState.WAITING:
            if is_speech:
                self._state = VADState.SPEAKING
                self._speech_started_time = now
                self._silence_started_time = None
                self._total_speech_bytes += len(chunk)
                self._speech_just_started = True
                self.current_vad_event = "speech_started"
                logger.debug("VAD: Speech onset detected (RMS=%.1f, thr=%.1f)", rms, onset_threshold)
            else:
                self._adapt_noise_floor(rms)

        elif self._state == VADState.SPEAKING:
            if is_speech:
                self._silence_started_time = None
                self._total_speech_bytes += len(chunk)
                self.current_vad_event = "speech_continues"
            else:
                self._state = VADState.SILENCE
                self._silence_started_time = now
                self.current_vad_event = "silence_started"
                logger.debug("VAD: Transitioned SPEAKING -> SILENCE (RMS=%.1f)", rms)

        elif self._state == VADState.SILENCE:
            if is_speech:
                # User resumed speaking before silence timeout expired
                self._state = VADState.SPEAKING
                self._silence_started_time = None
                self._total_speech_bytes += len(chunk)
                self.current_vad_event = "speech_continues"
                logger.debug("VAD: Speech resumed from SILENCE (RMS=%.1f)", rms)
            else:
                elapsed_silence = now - (self._silence_started_time or now)
                speech_duration = (
                    (self._silence_started_time - (self._speech_started_time or now))
                    if self._speech_started_time and self._silence_started_time
                    else 0.0
                )

                if elapsed_silence >= self.silence_timeout:
                    if speech_duration >= self.min_speech_duration:
                        self._state = VADState.COMPLETED
                        self._speech_confirmed = True
                        self.last_speech_seconds = speech_duration
                        self.completion_reason = "speech_end"
                        self.current_vad_event = "speech_ended"
                        logger.info(
                            "VAD: Utterance completed (speech=%.2fs, silence=%.2fs)",
                            speech_duration,
                            elapsed_silence,
                        )
                    else:
                        # Noise spike was shorter than min_speech_duration; discard and wait
                        logger.debug("VAD: Noise transient ignored (duration=%.2fs). Resetting to WAITING.", speech_duration)
                        self._reset_utterance()
                        self.current_vad_event = "noise_discarded"
                else:
                    self.current_vad_event = "speech_continues"

        return self._state


class MockVAD(VoiceActivityDetectorInterface):
    """Deterministic mock VAD for unit testing without audio signal processing."""

    def __init__(self, predefined_transitions: Optional[list[VADState]] = None) -> None:
        self._predefined = list(predefined_transitions or [])
        self._index = 0
        self._state: VADState = VADState.WAITING
        self.current_vad_event = "none"

    @property
    def state(self) -> VADState:
        return self._state

    @property
    def is_speech_started(self) -> bool:
        return self._state == VADState.SPEAKING

    @property
    def is_speech_active(self) -> bool:
        return self._state in (VADState.SPEAKING, VADState.SILENCE)

    @property
    def is_speech_ended(self) -> bool:
        return self._state == VADState.COMPLETED

    def reset(self) -> None:
        self._index = 0
        self._state = VADState.WAITING
        self.current_vad_event = "none"

    def set_state(self, state: VADState) -> None:
        """Explicitly inject a state for test scenarios."""
        self._state = state

    def process_chunk(self, chunk: bytes) -> VADState:
        if self._index < len(self._predefined):
            self._state = self._predefined[self._index]
            self._index += 1
        if self._state == VADState.SPEAKING:
            self.current_vad_event = "speech_continues"
        elif self._state == VADState.COMPLETED:
            self.current_vad_event = "speech_ended"
        return self._state
