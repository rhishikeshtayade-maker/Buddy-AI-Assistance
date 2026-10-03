"""BUDDY Wake Word Detection Subsystem.

Defines wake word detection interface, mock wake word detector for CI,
and keyword-based wake word detector.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional

from app.voice.models import AudioData

logger = logging.getLogger("buddy.voice.wake")


class WakeWordDetector(ABC):
    """Abstract interface for wake word detection."""

    @property
    @abstractmethod
    def wake_word(self) -> str:
        """The trigger phrase recognized by this detector."""

    @abstractmethod
    async def detect(self, audio: AudioData) -> bool:
        """Analyze an AudioData buffer and determine if the wake word is present."""


class MockWakeWordDetector(WakeWordDetector):
    """Deterministic mock detector for unit tests."""

    def __init__(self, wake_word: str = "hey buddy", default_result: bool = True) -> None:
        self._wake_word = wake_word.strip().lower()
        self.default_result = default_result
        self.detect_call_count = 0

    @property
    def wake_word(self) -> str:
        return self._wake_word

    def set_result(self, result: bool) -> None:
        self.default_result = result

    async def detect(self, audio: AudioData) -> bool:
        self.detect_call_count += 1
        return self.default_result


class KeywordWakeWordDetector(WakeWordDetector):
    """Wake-word detector using an underlying STT provider to check for trigger words."""

    def __init__(self, stt_provider: Any, wake_word: str = "hey buddy") -> None:
        self._stt = stt_provider
        self._wake_word = wake_word.strip().lower()

    @property
    def wake_word(self) -> str:
        return self._wake_word

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
