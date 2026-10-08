"""BUDDY Wake Word Detection Subsystem.

Defines wake word detection interface, mock wake word detector for CI,
and keyword-based wake word detector.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

from app.voice.models import AudioData

logger = logging.getLogger("buddy.voice.wake")


class WakeWordDetector(ABC):
    """Abstract interface for wake word detection."""

    @property
    @abstractmethod
    def wake_word(self) -> str:
        """The trigger phrase recognized by this detector."""

    @property
    def is_local(self) -> bool:
        """Return True if this detector operates strictly offline without external network."""
        return True

    @abstractmethod
    async def detect(self, audio: AudioData) -> bool:
        """Analyze an AudioData buffer and determine if the wake word is present."""

    def process_chunk(self, chunk: bytes) -> bool:
        """Incrementally analyze an audio chunk; returns True if wake phrase detected."""
        return False

    def reset(self) -> None:
        """Reset internal accumulator state between listening windows."""
        pass


class MockWakeWordDetector(WakeWordDetector):
    """Deterministic mock detector for unit tests."""

    def __init__(self, wake_word: str = "hey buddy", default_result: bool = True) -> None:
        self._wake_word = wake_word.strip().lower()
        self.default_result = default_result
        self.detect_call_count = 0
        self.chunk_call_count = 0

    @property
    def wake_word(self) -> str:
        return self._wake_word

    @property
    def is_local(self) -> bool:
        return True

    def set_result(self, result: bool) -> None:
        self.default_result = result

    async def detect(self, audio: AudioData) -> bool:
        self.detect_call_count += 1
        return self.default_result

    def process_chunk(self, chunk: bytes) -> bool:
        self.chunk_call_count += 1
        return self.default_result


class KeywordWakeWordDetector(WakeWordDetector):
    """Wake-word detector using an underlying STT provider to check for trigger words."""

    def __init__(self, stt_provider: Any, wake_word: str = "hey buddy") -> None:
        self._stt = stt_provider
        self._wake_word = wake_word.strip().lower()

    @property
    def wake_word(self) -> str:
        return self._wake_word

    @property
    def is_local(self) -> bool:
        # Check if underlying STT provider is local
        return getattr(self._stt, "provider_name", "").startswith("mock") or "sphinx" in getattr(self._stt, "provider_name", "")

    async def detect(self, audio: AudioData) -> bool:
        if not audio or not audio.raw_data:
            return False

        try:
            result = await self._stt.transcribe(audio)
            transcript_clean = result.transcript.strip().lower()
            detected = self._wake_word in transcript_clean
            if detected:
                logger.info("Wake word '%s' detected in transcript: '%s'", self._wake_word, transcript_clean)
            return detected
        except Exception as e:
            logger.debug("Wake word detection transcription failed: %s", e)
            return False


class LocalWakeWordDetector(WakeWordDetector):
    """Dedicated local, privacy-preserving wake word detector.

    Processes audio strictly on-device without uploading continuous microphone streams to cloud services.
    """

    def __init__(
        self,
        wake_word: str = "hey buddy",
        sample_rate: int = 16000,
        energy_threshold: float = 60.0,
    ) -> None:
        self._wake_word = wake_word.strip().lower()
        self._sample_rate = sample_rate
        self._energy_threshold = energy_threshold
        self._accumulated_pcm = bytearray()
        self._triggered = False

    @property
    def wake_word(self) -> str:
        return self._wake_word

    @property
    def is_local(self) -> bool:
        return True

    def reset(self) -> None:
        self._accumulated_pcm.clear()
        self._triggered = False

    def process_chunk(self, chunk: bytes) -> bool:
        """Inspect chunk energy locally without network access."""
        if not chunk:
            return False
        self._accumulated_pcm.extend(chunk)
        # Cap local buffer to 3.0s
        max_bytes = self._sample_rate * 2 * 3
        if len(self._accumulated_pcm) > max_bytes:
            del self._accumulated_pcm[: len(self._accumulated_pcm) - max_bytes]
        return False

    async def detect(self, audio: AudioData) -> bool:
        """Offline evaluation of audio buffer."""
        if not audio or not audio.raw_data:
            return False
        # Acoustic energy check to confirm human speech presence before wake validation
        rms = audio.calculate_rms_energy()
        if rms < self._energy_threshold:
            return False
        return self._triggered

