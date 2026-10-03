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
from typing import Optional

from app.voice.exceptions import STTError
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
    """Speech-to-Text provider backed by the Python speech_recognition library."""

    def __init__(self, engine: str = "google", timeout: float = 10.0) -> None:
        self._engine = engine
        self._timeout = timeout
        self._recognizer: Optional[Any] = None

    @property
    def provider_name(self) -> str:
        return f"speech_recognition_{self._engine}"

    def _get_recognizer(self) -> Any:
        if self._recognizer is None:
            try:
                import speech_recognition as sr
                self._recognizer = sr.Recognizer()
            except ImportError as err:
                raise STTError("speech_recognition package is not installed") from err
        return self._recognizer

    async def transcribe(self, audio: AudioData, language: Optional[str] = "en") -> STTResult:
        if not audio or not audio.raw_data or len(audio.raw_data) < 100:
            raise STTError("Audio buffer contains insufficient audio data for transcription")

        import speech_recognition as sr

        recognizer = self._get_recognizer()

        # Wrap audio data into speech_recognition AudioData container
        sr_audio = sr.AudioData(
            frame_data=audio.raw_data,
            sample_rate=audio.sample_rate,
            sample_width=audio.sample_width,
        )

        loop = asyncio.get_running_loop()

        def _do_transcribe() -> str:
            if self._engine == "google":
                return recognizer.recognize_google(
                    sr_audio,
                    language=language or "en-US",
                )
            elif self._engine == "sphinx":
                return recognizer.recognize_sphinx(sr_audio)
            else:
                raise STTError(f"Unsupported speech_recognition engine: '{self._engine}'")

        try:
            # Run in worker thread to prevent blocking the async event loop
            transcript = await asyncio.wait_for(
                loop.run_in_executor(None, _do_transcribe),
                timeout=self._timeout,
            )

            if not transcript or not transcript.strip():
                raise STTError("STT returned empty transcript")

            return STTResult(
                transcript=transcript.strip(),
                confidence=0.85,
                language=language or "en",
                duration=audio.duration,
                provider=self.provider_name,
                timestamp=time.time(),
            )

        except asyncio.TimeoutError:
            raise STTError(f"Transcription timed out after {self._timeout}s")
        except sr.UnknownValueError:
            # Speech was unintelligible
            raise STTError("Audio was unintelligible or contained no recognizable speech")
        except sr.RequestError as e:
            # Network error or recognition service unavailable
            raise STTError(f"STT recognition service error: {e}")
        except Exception as e:
            if isinstance(e, STTError):
                raise
            raise STTError(f"STT transcription failed: {e}") from e
