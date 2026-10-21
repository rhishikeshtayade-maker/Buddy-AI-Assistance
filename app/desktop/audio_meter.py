"""BUDDY Audio Level Meter.

Provides real-time RMS energy metering for audio-reactive waveforms and orb pulsing.
Processes audio buffers purely in-memory; raw audio frames are immediately discarded
after computing scalar amplitude metrics (0.0 to 1.0).
"""

from __future__ import annotations

import math
import struct
from typing import Optional

from app.voice.capture import AudioCaptureInterface
from app.voice.models import AudioData


def calculate_rms_normalized(
    pcm_bytes: bytes,
    sample_width: int = 2,
    max_expected_rms: float = 3000.0,
) -> float:
    """Calculate normalized RMS level [0.0, 1.0] from 16-bit PCM chunk."""
    if not pcm_bytes or len(pcm_bytes) < sample_width:
        return 0.0

    count = len(pcm_bytes) // sample_width
    usable_bytes = count * sample_width

    try:
        samples = struct.unpack(f"<{count}h", pcm_bytes[:usable_bytes])
        if not samples:
            return 0.0
        sum_sq = sum(s * s for s in samples)
        rms = math.sqrt(sum_sq / count)
        # Normalize and clamp into [0.0, 1.0]
        normalized = min(1.0, max(0.0, rms / max_expected_rms))
        return normalized
    except Exception:
        return 0.0


class MeteredAudioCapture(AudioCaptureInterface):
    """Transparent proxy over an AudioCaptureInterface that extracts scalar RMS levels.
    
    Raw audio passes straight through without retention or disk writes.
    """

    def __init__(self, target: AudioCaptureInterface, smoothing: float = 0.3) -> None:
        self._target = target
        self._smoothing = smoothing
        self._current_level: float = 0.0

    @property
    def target(self) -> AudioCaptureInterface:
        return self._target

    @property
    def current_level(self) -> float:
        """Normalized audio energy level [0.0, 1.0]."""
        return self._current_level

    def reset_level(self) -> None:
        self._current_level = 0.0

    async def start(self) -> None:
        self.reset_level()
        await self._target.start()

    async def stop(self) -> AudioData:
        self.reset_level()
        return await self._target.stop()

    async def cancel(self) -> None:
        self.reset_level()
        await self._target.cancel()

    async def read_chunk(self, timeout: Optional[float] = None) -> bytes:
        chunk = await self._target.read_chunk(timeout=timeout)
        instant_level = calculate_rms_normalized(chunk)
        # Exponential smoothing: new_level = alpha * instant + (1 - alpha) * current
        self._current_level = (self._smoothing * instant_level) + ((1.0 - self._smoothing) * self._current_level)
        return chunk

    @property
    def is_capturing(self) -> bool:
        return self._target.is_capturing

    @property
    def sample_rate(self) -> int:
        return self._target.sample_rate

    @property
    def channels(self) -> int:
        return self._target.channels
