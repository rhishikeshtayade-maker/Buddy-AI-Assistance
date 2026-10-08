"""BUDDY Text-to-Speech (TTS) Subsystem.

Defines provider interface, mock TTS provider with interruption tracking,
and offline pyttsx3 speech synthesis.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import AsyncIterator, Callable, List, Optional

from app.voice.exceptions import TTSError
from app.voice.models import AudioData

logger = logging.getLogger("buddy.voice.tts")


async def clause_stream_from_tokens(token_stream: AsyncIterator[str]) -> AsyncIterator[str]:
    """Buffer incoming word/subword tokens into coherent clauses/sentences for low-latency streaming TTS."""
    buf: List[str] = []
    word_count = 0
    sentence_delims = {".", "!", "?", "\n"}
    clause_delims = {",", ";", ":"}

    async for token in token_stream:
        buf.append(token)
        if " " in token:
            word_count += token.count(" ")

        has_sentence = any(d in token for d in sentence_delims)
        has_clause = any(d in token for d in clause_delims) and word_count >= 5

        if has_sentence or has_clause:
            clause = "".join(buf).strip()
            if clause:
                yield clause
            buf.clear()
            word_count = 0

    if buf:
        remaining = "".join(buf).strip()
        if remaining:
            yield remaining


class TextToSpeechProvider(ABC):
    """Abstract interface defining text-to-speech synthesis and playback."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the TTS provider."""

    @property
    def supports_streaming(self) -> bool:
        """Return True if this provider supports incremental token stream playback."""
        return True

    @property
    @abstractmethod
    def is_speaking(self) -> bool:
        """Return True if audio playback or synthesis is currently active."""

    @abstractmethod
    async def synthesize(self, text: str) -> AudioData:
        """Synthesize text into raw PCM AudioData buffer."""

    @abstractmethod
    async def speak(self, text: str, interruptible: bool = True) -> None:
        """Voicing text through speaker endpoint with interruption capability."""

    async def speak_stream(
        self,
        token_stream: AsyncIterator[str],
        interruptible: bool = True,
        on_first_audio: Optional[Callable[[], Any]] = None,
    ) -> None:
        """Streamingly ingest text tokens, chunk into sentences/clauses, and voice incrementally."""
        first_fired = False
        async for clause in clause_stream_from_tokens(token_stream):
            if not first_fired and on_first_audio:
                first_fired = True
                res = on_first_audio()
                if asyncio.iscoroutine(res):
                    await res
            await self.speak(clause, interruptible=interruptible)

    @abstractmethod
    async def stop(self) -> None:
        """Immediately interrupt and halt any ongoing speech playback."""



class MockTTSProvider(TextToSpeechProvider):
    """Deterministic mock TTS provider for automated tests and CI."""

    def __init__(
        self,
        simulate_failure: bool = False,
        speech_delay: float = 0.05,
    ) -> None:
        self.simulate_failure = simulate_failure
        self.speech_delay = speech_delay
        self._spoken_phrases: List[str] = []
        self._is_speaking = False
        self._interrupted = False
        self._stop_event = asyncio.Event()

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    @property
    def spoken_phrases(self) -> List[str]:
        return list(self._spoken_phrases)

    @property
    def was_interrupted(self) -> bool:
        return self._interrupted

    def clear(self) -> None:
        self._spoken_phrases.clear()
        self._interrupted = False

    async def synthesize(self, text: str) -> AudioData:
        if self.simulate_failure:
            raise TTSError("Simulated TTS synthesis failure")
        if not text or not text.strip():
            raise TTSError("Cannot synthesize empty text")

        # Produce 0.1s synthetic 16kHz audio buffer
        num_samples = int(16000 * 0.1)
        raw_pcm = b"\x00\x00" * num_samples
        return AudioData(raw_data=raw_pcm, sample_rate=16000, sample_width=2, channels=1)

    async def speak(self, text: str, interruptible: bool = True) -> None:
        if self.simulate_failure:
            raise TTSError("Simulated TTS speech playback failure")
        if not text or not text.strip():
            raise TTSError("Cannot speak empty text")

        self._is_speaking = True
        self._interrupted = False
        self._stop_event.clear()

        try:
            # Simulate speech progression with cancellation check
            steps = 5
            step_duration = self.speech_delay / steps
            for _ in range(steps):
                if self._stop_event.is_set():
                    self._interrupted = True
                    logger.info("MockTTS: Speech playback interrupted for: '%s'", text)
                    return
                await asyncio.sleep(step_duration)

            self._spoken_phrases.append(text)
            logger.debug("MockTTS: Spoke phrase: '%s'", text)
        finally:
            self._is_speaking = False

    async def speak_stream(
        self,
        token_stream: AsyncIterator[str],
        interruptible: bool = True,
        on_first_audio: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._is_speaking = True
        self._interrupted = False
        self._stop_event.clear()
        first_fired = False

        try:
            async for clause in clause_stream_from_tokens(token_stream):
                if self._stop_event.is_set():
                    self._interrupted = True
                    break
                if not first_fired and on_first_audio:
                    first_fired = True
                    res = on_first_audio()
                    if asyncio.iscoroutine(res):
                        await res
                await self.speak(clause, interruptible=interruptible)
                if self._interrupted:
                    break
        finally:
            self._is_speaking = False

    async def stop(self) -> None:
        self._stop_event.set()
        self._is_speaking = False
        logger.debug("MockTTS: stop() invoked.")


class Pyttsx3TTSProvider(TextToSpeechProvider):
    """Local, offline Text-to-Speech provider backed by pyttsx3.

    Loop 13 hardening:
      - Never speaks raw secrets (passed through redact_string before synthesis).
      - Handles empty/whitespace text gracefully without raising fatal exceptions.
      - Tracks active engine reference for immediate cancellation on stop().
      - Non-blocking execution in executor thread.
      - Prevents engine resource leak.
    """

    def __init__(
        self,
        rate: int = 175,
        volume: float = 1.0,
        voice_id: Optional[str] = None,
    ) -> None:
        self._rate = rate
        self._volume = volume
        self._voice_id = voice_id
        self._is_speaking = False
        self._active_engine: Optional[Any] = None
        self._lock = threading.Lock()
        self._stop_requested = False

    @property
    def provider_name(self) -> str:
        return "pyttsx3"

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    def _init_engine(self) -> Any:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", self._rate)
        engine.setProperty("volume", self._volume)
        if self._voice_id:
            engine.setProperty("voice", self._voice_id)
        return engine

    async def synthesize(self, text: str) -> AudioData:
        if not text or not text.strip():
            raise TTSError("Cannot synthesize empty text")

        # Pyttsx3 does direct audio output; for synthesis to buffer, generate short synthetic PCM buffer
        num_samples = int(16000 * 0.1)
        raw_pcm = b"\x00\x00" * num_samples
        return AudioData(raw_data=raw_pcm, sample_rate=16000, sample_width=2, channels=1)

    async def speak(self, text: str, interruptible: bool = True) -> None:
        if not text or not text.strip():
            logger.debug("Pyttsx3TTSProvider: empty text passed, skipping.")
            return

        # Security check: redact any secrets before speech output
        from app.security.secrets.redaction import redact_string
        safe_text = redact_string(text.strip())

        self._is_speaking = True
        self._stop_requested = False

        loop = asyncio.get_running_loop()

        def _do_speak() -> None:
            with self._lock:
                if self._stop_requested:
                    return
                try:
                    engine = self._init_engine()
                    self._active_engine = engine
                except Exception as e:
                    logger.warning("Failed to initialize pyttsx3 engine: %s", e)
                    return

            try:
                if not self._stop_requested and self._active_engine:
                    self._active_engine.say(safe_text)
                    self._active_engine.runAndWait()
            except Exception as e:
                logger.warning("pyttsx3 speech error: %s", e)
            finally:
                with self._lock:
                    if self._active_engine:
                        try:
                            self._active_engine.stop()
                        except Exception:
                            pass
                        self._active_engine = None

        try:
            await loop.run_in_executor(None, _do_speak)
        except Exception as e:
            logger.error("TTS playback error: %s", e)
            raise TTSError(f"TTS playback error: {e}") from e
        finally:
            self._is_speaking = False

    async def speak_stream(
        self,
        token_stream: AsyncIterator[str],
        interruptible: bool = True,
        on_first_audio: Optional[Callable[[], Any]] = None,
    ) -> None:
        self._is_speaking = True
        self._stop_requested = False
        first_fired = False

        try:
            async for clause in clause_stream_from_tokens(token_stream):
                if self._stop_requested:
                    break
                if not first_fired and on_first_audio:
                    first_fired = True
                    res = on_first_audio()
                    if asyncio.iscoroutine(res):
                        await res
                await self.speak(clause, interruptible=interruptible)
                if self._stop_requested:
                    break
        finally:
            self._is_speaking = False

    async def stop(self) -> None:
        """Interrupt and halt any active speech playback."""
        self._stop_requested = True
        self._is_speaking = False
        with self._lock:
            if self._active_engine is not None:
                try:
                    self._active_engine.stop()
                except Exception as e:
                    logger.debug("Error stopping active pyttsx3 engine: %s", e)
