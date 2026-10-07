"""BUDDY Speech-to-Text (STT) Subsystem.

Defines provider interface, mock STT provider for CI tests, and
SpeechRecognition provider implementation.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from app.voice.exceptions import (
    STTEmptyError,
    STTError,
    STTServiceError,
    STTTimeoutError,
    STTUnclearError,
)
from app.voice.models import AudioData, STTResult

logger = logging.getLogger("buddy.voice.stt")


class SpeechToTextProvider(ABC):
    """Abstract interface defining speech-to-text transcription."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the STT provider."""

    @abstractmethod
    async def transcribe(self, audio: AudioData, language: Optional[str] = "en") -> STTResult:
        """Transcribe an AudioData buffer into an STTResult.

        Raises STTError on failure or timeout.
        """


class MockSTTProvider(SpeechToTextProvider):
    """Deterministic mock STT provider for automated testing."""

    def __init__(
        self,
        default_transcript: str = "Hello BUDDY",
        confidence: float = 0.98,
        simulate_failure: bool = False,
        failure_exception: Optional[Exception] = None,
        latency: float = 0.0,
    ) -> None:
        self.default_transcript = default_transcript
        self.confidence = confidence
        self.simulate_failure = simulate_failure
        self.failure_exception = failure_exception
        self.latency = latency
        self.transcribe_call_count = 0
        self.last_audio_received: Optional[AudioData] = None

    @property
    def provider_name(self) -> str:
        return "mock"

    def set_next_transcript(self, transcript: str, confidence: float = 0.98) -> None:
        """Queue a specific transcript for the next call."""
        self.default_transcript = transcript
        self.confidence = confidence

    async def transcribe(self, audio: AudioData, language: Optional[str] = "en") -> STTResult:
        self.transcribe_call_count += 1
        self.last_audio_received = audio

        if self.latency > 0:
            await asyncio.sleep(self.latency)

        if self.simulate_failure:
            err = self.failure_exception or STTError("Simulated mock STT provider failure")
            raise err

        if not audio or not audio.raw_data:
            raise STTError("Empty audio buffer supplied to STT provider")

        return STTResult(
            transcript=self.default_transcript,
            confidence=self.confidence,
            language=language or "en",
            duration=audio.duration,
            provider=self.provider_name,
            timestamp=time.time(),
        )


class SpeechRecognitionSTTProvider(SpeechToTextProvider):
    """Speech-to-Text provider backed by the Python speech_recognition library.

    Failure categories (all subclasses of STTError):
      - STTEmptyError:   audio too short / provider returned nothing
      - STTUnclearError: speech present but unintelligible
      - STTServiceError: network / service / quota failure
      - STTTimeoutError: bounded recognition timeout exceeded

    Audio is held in memory only for the duration of the request; it is never
    written to disk or logged.
    """

    # Minimum audio accepted for transcription (~0.15s of 16 kHz mono PCM16).
    MIN_AUDIO_SECONDS = 0.15

    def __init__(self, engine: str = "google", timeout: float = 10.0) -> None:
        self._engine = engine
        self._timeout = timeout
        self._recognizer: Optional[Any] = None

    @property
    def provider_name(self) -> str:
        return f"speech_recognition_{self._engine}"

    @property
    def timeout(self) -> float:
        return self._timeout

    def _get_recognizer(self) -> Any:
        if self._recognizer is None:
            try:
                import speech_recognition as sr
                self._recognizer = sr.Recognizer()
                # Bound the underlying HTTP request so worker threads cannot hang forever.
                self._recognizer.operation_timeout = self._timeout
            except ImportError as err:
                raise STTServiceError("speech_recognition package is not installed") from err
        return self._recognizer

    @staticmethod
    def _normalize_language(language: Optional[str]) -> str:
        if not language or language.lower() == "en":
            return "en-US"
        return language

    async def transcribe(self, audio: AudioData, language: Optional[str] = "en") -> STTResult:
        if not audio or not audio.raw_data or len(audio.raw_data) < 100:
            raise STTEmptyError("Audio buffer contains insufficient audio data for transcription")
        if audio.duration < self.MIN_AUDIO_SECONDS:
            raise STTEmptyError(f"Audio too short for transcription ({audio.duration:.2f}s)")

        try:
            import speech_recognition as sr
        except ImportError as err:
            raise STTServiceError("speech_recognition package is not installed") from err

        recognizer = self._get_recognizer()

        # Wrap audio data into speech_recognition AudioData container (in memory only)
        sr_audio = sr.AudioData(
            frame_data=audio.raw_data,
            sample_rate=audio.sample_rate,
            sample_width=audio.sample_width,
        )
        lang = self._normalize_language(language)

        loop = asyncio.get_running_loop()

        def _do_transcribe() -> str:
            if self._engine == "google":
                return recognizer.recognize_google(sr_audio, language=lang)
            elif self._engine == "sphinx":
                return recognizer.recognize_sphinx(sr_audio)
            else:
                raise STTServiceError(f"Unsupported speech_recognition engine: '{self._engine}'")

        try:
            # Run in worker thread to prevent blocking the async event loop
            transcript = await asyncio.wait_for(
                loop.run_in_executor(None, _do_transcribe),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            raise STTTimeoutError(f"Transcription timed out after {self._timeout}s")
        except sr.UnknownValueError:
            raise STTUnclearError("Audio was unintelligible or contained no recognizable speech")
        except sr.RequestError as e:
            raise STTServiceError(f"STT recognition service error: {e}")
        except STTError:
            raise
        except (TimeoutError, OSError) as e:
            raise STTServiceError(f"STT network error: {e}") from e
        except Exception as e:
            raise STTServiceError(f"STT transcription failed: {e}") from e
        finally:
            del sr_audio

        if not isinstance(transcript, str) or not transcript.strip():
            raise STTEmptyError("STT returned empty transcript")

        return STTResult(
            transcript=transcript.strip(),
            confidence=None,  # Google free API does not expose a reliable confidence here
            language=lang,
            duration=audio.duration,
            provider=self.provider_name,
            timestamp=time.time(),
        )
