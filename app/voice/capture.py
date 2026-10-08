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
from typing import Any, AsyncIterator, Optional, Union

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

    async def stream_chunks(self) -> AsyncIterator[bytes]:
        """Asynchronously yield audio chunks while capturing."""
        while self.is_capturing:
            try:
                chunk = await self.read_chunk(timeout=0.1)
                yield chunk
            except asyncio.TimeoutError:
                continue
            except AudioCaptureError:
                break


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

    def set_canned_audio(self, audio: Optional[AudioData]) -> None:
        """Set pre-recorded audio data that will be fed during capture."""
        self._canned_audio = audio
        if audio is not None:
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
    """Hardware microphone audio capture utilizing sounddevice.

    Loop 13 hardening:
      * ``persistent=True`` keeps the PortAudio stream open between capture
        windows (opening the Realtek stream costs ~0.7s on real hardware, which
        otherwise clips the start of the user's speech). Frames are only
        *collected* between ``start()`` and ``stop()/cancel()``; outside a
        window the callback drops them immediately. ``close()`` must be called
        at shutdown to release the device.
      * Bounded frame queue (drop-oldest on overflow) and bounded accumulation
        buffer, so a stalled consumer can never grow memory without limit.
      * Frame counters (``total_chunks_received``, ``window_chunks_received``,
        ``overflow_count``) prove that real frames are arriving.
      * Start-up warm-up frames are discarded after a stream (re)opens.
      * Audio is held in memory only; it is never written to disk or logged.
    """

    def __init__(
        self,
        device_id: Optional[Union[int, str]] = None,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 1024,
        chunk_ms: Optional[int] = None,
        persistent: bool = False,
        max_queue_chunks: int = 256,
        max_buffer_seconds: float = 30.0,
        warmup_seconds: float = 0.1,
    ) -> None:
        self._device_id = device_id
        self._sample_rate = sample_rate
        self._channels = channels
        if chunk_ms is not None and chunk_ms > 0:
            self._chunk_size = max(64, int(sample_rate * (chunk_ms / 1000.0)))
        else:
            self._chunk_size = chunk_size
        self._sample_width = 2
        self._persistent = persistent
        self._max_buffer_bytes = int(max_buffer_seconds * sample_rate * channels * self._sample_width)
        self._warmup_bytes = int(warmup_seconds * sample_rate * channels * self._sample_width)

        self._stream: Optional[Any] = None
        self._queue: queue.Queue[bytes] = queue.Queue(maxsize=max_queue_chunks)
        self._is_capturing = False
        self._accumulated_bytes = bytearray()
        self._lock = asyncio.Lock()
        self._warmup_remaining = 0

        # Diagnostics (numeric only; no audio content)
        self.total_chunks_received = 0
        self.window_chunks_received = 0
        self.overflow_count = 0
        self.status_warning_count = 0
        self.streams_opened = 0
        self.streams_closed = 0
        self.last_open_latency: float = 0.0
        self.resolved_device_index: Optional[int] = None

    @property
    def is_capturing(self) -> bool:
        return self._is_capturing

    @property
    def is_stream_open(self) -> bool:
        return self._stream is not None

    @property
    def persistent(self) -> bool:
        return self._persistent

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    def _audio_callback(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        """Callback invoked by portaudio in a separate OS audio thread."""
        if status:
            self.status_warning_count += 1
        if not self._is_capturing:
            return
        raw_pcm = bytes(indata)
        if self._warmup_remaining > 0:
            self._warmup_remaining -= len(raw_pcm)
            return
        self.total_chunks_received += 1
        try:
            self._queue.put_nowait(raw_pcm)
        except queue.Full:
            # Drop the oldest chunk to keep latency bounded
            self.overflow_count += 1
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(raw_pcm)
            except (queue.Empty, queue.Full):
                pass

    def _drain_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _resolve_device(self, sd: Any) -> Optional[int]:
        if self._device_id is None or str(self._device_id).lower() == "default":
            return None
        if isinstance(self._device_id, int):
            return self._device_id
        if str(self._device_id).isdigit():
            return int(str(self._device_id))
        devices = sd.query_devices()
        for idx, d in enumerate(devices):
            if str(self._device_id).lower() in d["name"].lower() and d["max_input_channels"] > 0:
                return idx
        raise AudioDeviceError(f"Input device '{self._device_id}' not found", device_name=str(self._device_id))

    async def _open_stream_locked(self) -> None:
        if self._stream is not None:
            return
        try:
            import sounddevice as sd
        except ImportError as err:
            raise AudioCaptureError("sounddevice package is required for hardware capture") from err

        dev_idx = self._resolve_device(sd)
        self.resolved_device_index = dev_idx
        t0 = time.perf_counter()
        stream = None
        try:
            stream = sd.RawInputStream(
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype="int16",
                blocksize=self._chunk_size,
                device=dev_idx,
                callback=self._audio_callback,
            )
            stream.start()
        except Exception as e:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            raise AudioCaptureError(f"Failed to initialize audio capture stream: {e}") from e
        self._stream = stream
        self.streams_opened += 1
        self._warmup_remaining = self._warmup_bytes
        self.last_open_latency = time.perf_counter() - t0
        logger.info(
            "SoundDeviceAudioCapture stream opened (device=%s, rate=%d, channels=%d, %.0f ms)",
            dev_idx,
            self._sample_rate,
            self._channels,
            self.last_open_latency * 1000,
        )

    def _close_stream_locked(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.stop()
        except Exception as e:
            logger.warning("Error stopping audio stream: %s", e)
        try:
            stream.close()
        except Exception as e:
            logger.warning("Error closing audio stream: %s", e)
        self.streams_closed += 1
        logger.info("SoundDeviceAudioCapture stream closed.")

    async def open(self) -> None:
        """Open (and keep open) the underlying stream without starting collection."""
        async with self._lock:
            await self._open_stream_locked()

    async def close(self) -> None:
        """Fully release the microphone. Idempotent; safe to call at shutdown."""
        async with self._lock:
            self._is_capturing = False
            self._close_stream_locked()
            self._drain_queue()
            self._accumulated_bytes.clear()

    async def start(self) -> None:
        async with self._lock:
            self._accumulated_bytes.clear()
            self._drain_queue()
            self.window_chunks_received = 0
            if not self._is_capturing:
                try:
                    await self._open_stream_locked()
                except Exception:
                    self._is_capturing = False
                    raise
                self._drain_queue()
                self._is_capturing = True

    async def stop(self) -> AudioData:
        async with self._lock:
            was_capturing = self._is_capturing
            self._is_capturing = False
            if not self._persistent:
                self._close_stream_locked()

            if was_capturing:
                # Drain any remaining chunks in queue
                while True:
                    try:
                        self._append_bounded(self._queue.get_nowait())
                    except queue.Empty:
                        break

            data = bytes(self._accumulated_bytes)
            self._accumulated_bytes.clear()
            logger.debug("SoundDeviceAudioCapture window stopped. Duration: %.2fs", len(data) / (self._sample_rate * 2))
            return AudioData(
                raw_data=data,
                sample_rate=self._sample_rate,
                sample_width=self._sample_width,
                channels=self._channels,
            )

    async def cancel(self) -> None:
        async with self._lock:
            self._is_capturing = False
            if not self._persistent:
                self._close_stream_locked()
            self._accumulated_bytes.clear()
            self._drain_queue()
            logger.debug("SoundDeviceAudioCapture window cancelled.")

    def _append_bounded(self, chunk: bytes) -> None:
        self._accumulated_bytes.extend(chunk)
        overflow = len(self._accumulated_bytes) - self._max_buffer_bytes
        if overflow > 0:
            del self._accumulated_bytes[:overflow]

    async def read_chunk(self, timeout: Optional[float] = None) -> bytes:
        if not self._is_capturing:
            raise AudioCaptureError("Audio capture is not active")

        deadline = (time.monotonic() + timeout) if timeout else None

        while self._is_capturing:
            try:
                chunk = self._queue.get_nowait()
                self._append_bounded(chunk)
                self.window_chunks_received += 1
                return chunk
            except queue.Empty:
                if deadline and time.monotonic() > deadline:
                    raise asyncio.TimeoutError("Timeout waiting for audio chunk")
                await asyncio.sleep(0.002)

        raise AudioCaptureError("Capture stopped while waiting for chunk")
