"""Unit tests for BUDDY Text-to-Speech (TTS) Subsystem."""

import asyncio
import unittest
from app.voice import (
    AudioData,
    MockTTSProvider,
    TTSError,
)


class TestTextToSpeech(unittest.IsolatedAsyncioTestCase):
    """Test suite verifying TTS synthesis, voicing, cancellation, and error conditions."""

    async def asyncSetUp(self) -> None:
        self.mock_tts = MockTTSProvider(speech_delay=0.05)

    async def test_successful_synthesis(self) -> None:
        """Verify synthesizing text produces AudioData buffer."""
        audio = await self.mock_tts.synthesize("Hello from BUDDY")
        self.assertIsInstance(audio, AudioData)
        self.assertGreater(len(audio.raw_data), 0)

    async def test_empty_text_raises_tts_error(self) -> None:
        """Verify empty or blank text raises TTSError."""
        with self.assertRaises(TTSError):
            await self.mock_tts.synthesize("")

        with self.assertRaises(TTSError):
            await self.mock_tts.speak("   ")

    async def test_successful_speak_records_phrases(self) -> None:
        """Verify speak() tracks completed phrases in history."""
        self.assertFalse(self.mock_tts.is_speaking)

        await self.mock_tts.speak("First phrase")
        await self.mock_tts.speak("Second phrase")

        self.assertEqual(self.mock_tts.spoken_phrases, ["First phrase", "Second phrase"])
        self.assertFalse(self.mock_tts.is_speaking)

    async def test_speech_interruption_support(self) -> None:
        """Verify stop() halts ongoing speech and sets was_interrupted flag."""
        tts = MockTTSProvider(speech_delay=0.2)

        async def speak_task():
            await tts.speak("A very long sentence that will be interrupted midway.")

        task = asyncio.create_task(speak_task())
        await asyncio.sleep(0.05)
        self.assertTrue(tts.is_speaking)

        # User interrupts speaking
        await tts.stop()
        await task

        self.assertTrue(tts.was_interrupted)
        self.assertFalse(tts.is_speaking)
        # Interrupted phrase is not appended as completed
        self.assertEqual(len(tts.spoken_phrases), 0)

    async def test_simulated_failure(self) -> None:
        """Verify simulated failure raises TTSError."""
        self.mock_tts.simulate_failure = True
        with self.assertRaises(TTSError):
            await self.mock_tts.speak("Test failure")


if __name__ == "__main__":
    unittest.main()
