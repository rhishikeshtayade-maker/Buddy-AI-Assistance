"""BUDDY Audio Capture Subsystem.

Provides asynchronous-friendly audio capture abstractions, mock audio generators
for deterministic CI testing, and hardware microphone capture via sounddevice.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import struct
import time
from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional, Union

from app.voice.exceptions import AudioCaptureError, AudioDeviceError
from app.voice.models import AudioData

logger = logging.getLogger("buddy.voice.capture")


class AudioCaptureInterface(ABC):
    """Abstract interface defining the audio capture contract."""

    @abstractmethod
    async def start(self) -> None:
        """Start capturing audio from the input source."""

    @abstractmethod
    async def stop(self) -> AudioData:
        """Stop capturing and return the accumulated AudioData buffer."""

    @abstractmethod
    async def cancel(self) -> None:
        """Cancel the current capture and discard any captured audio."""

    @abstractmethod
    async def read_chunk(self, timeout: Optional[float] = None) -> bytes:
        """Read a single chunk of PCM bytes from the audio stream."""

    @property
    @abstractmethod
    def is_capturing(self) -> bool:
        """Return whether audio capture is actively running."""

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Sample rate of captured audio."""

    @property
    @abstractmethod
    def channels(self) -> int:
        """Number of channels (e.g. 1 for mono)."""


class MockAudioCapture(AudioCaptureInterface):
    """Deterministic mock audio capture for unit tests and headless environments."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        sample_width: int = 2,
        canned_audio: Optional[AudioData] = None,
        chunk_size: int = 1024,
    ) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._sample_width = sample_width
        self._chunk_size = chunk_size
        self._is_capturing = False
        self._canned_audio = canned_audio
        self._accumulated_bytes = bytearray()
        self._cursor = 0

    @property
    def is_capturing(self) -> bool:
        return self._is_capturing

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    def set_canned_audio(self, audio: AudioData) -> None:
        """Set pre-recorded audio data that will be fed during capture."""
        self._canned_audio = audio
        self._sample_rate = audio.sample_rate
        self._channels = audio.channels
        self._sample_width = audio.sample_width

    async def start(self) -> None:
        self._is_capturing = True
        self._accumulated_bytes.clear()
        self._cursor = 0
        logger.debug("MockAudioCapture started (rate=%d, channels=%d)", self._sample_rate, self._channels)

    async def stop(self) -> AudioData:
        self._is_capturing = False
        logger.debug("MockAudioCapture stopped. Produced %d bytes", len(self._accumulated_bytes))
        return AudioData(
            raw_data=bytes(self._accumulated_bytes),
            sample_rate=self._sample_rate,
            sample_width=self._sample_width,
            channels=self._channels,
        )

    async def cancel(self) -> None:
        self._is_capturing = False
        self._accumulated_bytes.clear()
        self._cursor = 0
        logger.debug("MockAudioCapture cancelled.")

    async def read_chunk(self, timeout: Optional[float] = None) -> bytes:
        if not self._is_capturing:
            raise AudioCaptureError("Cannot read chunk: capture is not active")

        if self._canned_audio is not None:
            raw = self._canned_audio.raw_data
            if self._cursor >= len(raw):
                # Send silence once canned audio finishes
                chunk = b"\x00" * self._chunk_size
            else:
                chunk = raw[self._cursor : self._cursor + self._chunk_size]
                self._cursor += len(chunk)
                if len(chunk) < self._chunk_size:
                    chunk += b"\x00" * (self._chunk_size - len(chunk))
        else:
            # Generate synthetic low-level noise / silence
            chunk = b"\x00" * self._chunk_size

        self._accumulated_bytes.extend(chunk)
        await asyncio.sleep(0.001)  # Cooperative yield
        return chunk


class SoundDeviceAudioCapture(AudioCaptureInterface):
    """Hardware microphone audio capture utilizing sounddevice."""

    def __init__(
        self,
        device_id: Optional[Union[int, str]] = None,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 1024,
    ) -> None:
        self._device_id = device_id
        self._sample_rate = sample_rate
        self._channels = channels
        self._chunk_size = chunk_size
        self._sample_width = 2

        self._stream: Optional[Any] = None
        self._queue: queue.Queue[bytes] = queue.Queue()
        self._is_capturing = False
        self._accumulated_bytes = bytearray()
        self._lock = asyncio.Lock()

    @property
    def is_capturing(self) -> bool:
        return self._is_capturing

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    def _audio_callback(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        """Callback invoked by portaudio in a separate OS audio thread."""
        if status:
            logger.debug("SoundDevice status warning: %s", status)
        if self._is_capturing:
            # indata is float32 or int16 numpy array; convert to 16-bit PCM bytes
            raw_pcm = bytes(indata)
            self._queue.put_nowait(raw_pcm)

    async def start(self) -> None:
        async with self._lock:
            if self._is_capturing:
                return

            try:
                import sounddevice as sd
            except ImportError as err:
                raise AudioCaptureError("sounddevice package is required for hardware capture") from err

            # Resolve device ID if 'default' or str
            dev_idx = None
            if self._device_id is not None and str(self._device_id).lower() != "default":
                if isinstance(self._device_id, int):
                    dev_idx = self._device_id
                else:
                    # Resolve device by name
                    devices = sd.query_devices()
                    for idx, d in enumerate(devices):
                        if str(self._device_id).lower() in d["name"].lower() and d["max_input_channels"] > 0:
                            dev_idx = idx
                            break

            try:
                self._accumulated_bytes.clear()
                while not self._queue.empty():
                    self._queue.get_nowait()

                self._stream = sd.RawInputStream(
                    samplerate=self._sample_rate,
                    channels=self._channels,
                    dtype="int16",
                    blocksize=self._chunk_size,
                    device=dev_idx,
                    callback=self._audio_callback,
                )
                self._stream.start()
                self._is_capturing = True
                logger.info(
                    "SoundDeviceAudioCapture started (device=%s, rate=%d, channels=%d)",
                    dev_idx,
                    self._sample_rate,
                    self._channels,
                )
            except Exception as e:
                self._is_capturing = False
                raise AudioCaptureError(f"Failed to initialize audio capture stream: {e}") from e

    async def stop(self) -> AudioData:
        async with self._lock:
            if not self._is_capturing:
                return AudioData(
                    raw_data=bytes(self._accumulated_bytes),
                    sample_rate=self._sample_rate,
                    sample_width=self._sample_width,
                    channels=self._channels,
                )

            self._is_capturing = False
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception as e:
                    logger.warning("Error stopping audio stream: %s", e)
                finally:
                    self._stream = None

            # Drain any remaining chunks in queue
            while not self._queue.empty():
                try:
                    self._accumulated_bytes.extend(self._queue.get_nowait())
                except queue.Empty:
                    break

            logger.info("SoundDeviceAudioCapture stopped. Total duration: %.2fs", len(self._accumulated_bytes) / (self._sample_rate * 2))
            return AudioData(
                raw_data=bytes(self._accumulated_bytes),
                sample_rate=self._sample_rate,
                sample_width=self._sample_width,
                channels=self._channels,
            )

    async def cancel(self) -> None:
        async with self._lock:
            self._is_capturing = False
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception:
                    pass
                finally:
                    self._stream = None
            self._accumulated_bytes.clear()
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break
            logger.debug("SoundDeviceAudioCapture cancelled.")

    async def read_chunk(self, timeout: Optional[float] = None) -> bytes:
        if not self._is_capturing:
            raise AudioCaptureError("Audio capture is not active")

        loop = asyncio.get_running_loop()
        deadline = (time.time() + timeout) if timeout else None

        while self._is_capturing:
            try:
                chunk = self._queue.get_nowait()
                self._accumulated_bytes.extend(chunk)
                return chunk
            except queue.Empty:
                if deadline and time.time() > deadline:
                    raise asyncio.TimeoutError("Timeout waiting for audio chunk")
                await asyncio.sleep(0.01)

        raise AudioCaptureError("Capture stopped while waiting for chunk")
