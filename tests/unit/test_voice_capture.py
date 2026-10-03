"""Unit tests for BUDDY Audio Capture Subsystem."""

import asyncio
import unittest
from app.voice import (
    AudioCaptureError,
    AudioData,
    MockAudioCapture,
)


class TestAudioCapture(unittest.IsolatedAsyncioTestCase):
    """Test suite verifying audio capture start, stop, cancel, and mock buffer streaming."""

    async def asyncSetUp(self) -> None:
        self.capture = MockAudioCapture(sample_rate=16000, channels=1, chunk_size=1024)

    async def test_capture_lifecycle_start_stop(self) -> None:
        """Verify normal start and stop lifecycle returns populated AudioData."""
        self.assertFalse(self.capture.is_capturing)

        await self.capture.start()
        self.assertTrue(self.capture.is_capturing)

        # Read two chunks
        c1 = await self.capture.read_chunk()
        c2 = await self.capture.read_chunk()

        self.assertEqual(len(c1), 1024)
        self.assertEqual(len(c2), 1024)

        audio = await self.capture.stop()
        self.assertFalse(self.capture.is_capturing)
        self.assertIsInstance(audio, AudioData)
        self.assertEqual(len(audio.raw_data), 2048)
        self.assertAlmostEqual(audio.duration, 2048 / (16000 * 2), places=3)

    async def test_read_chunk_when_not_capturing_raises_error(self) -> None:
        """Verify read_chunk raises AudioCaptureError when not active."""
        with self.assertRaises(AudioCaptureError):
            await self.capture.read_chunk()

    async def test_capture_cancellation_discards_buffer(self) -> None:
        """Verify cancel() ceases capture and flushes accumulated audio."""
        await self.capture.start()
        await self.capture.read_chunk()
        await self.capture.read_chunk()

        await self.capture.cancel()
        self.assertFalse(self.capture.is_capturing)

        # Stopping after cancel produces empty audio
        audio = await self.capture.stop()
        self.assertEqual(len(audio.raw_data), 0)

    async def test_canned_audio_feeding(self) -> None:
        """Verify injected pre-recorded AudioData is streamed chunk-by-chunk."""
        fake_pcm = b"\x01\x02" * 1024  # 2048 bytes total
        canned = AudioData(raw_data=fake_pcm, sample_rate=16000, sample_width=2, channels=1)
        self.capture.set_canned_audio(canned)

        await self.capture.start()
        chunk1 = await self.capture.read_chunk()
        chunk2 = await self.capture.read_chunk()
        audio = await self.capture.stop()

        self.assertEqual(chunk1, fake_pcm[:1024])
        self.assertEqual(chunk2, fake_pcm[1024:2048])
        self.assertEqual(audio.raw_data, fake_pcm)


if __name__ == "__main__":
    unittest.main()
