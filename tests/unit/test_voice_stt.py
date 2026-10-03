"""Unit tests for BUDDY Speech-to-Text (STT) Subsystem."""

import asyncio
import unittest
from app.voice import (
    AudioData,
    MockSTTProvider,
    SpeechRecognitionSTTProvider,
    STTError,
    STTResult,
)


class TestSpeechToText(unittest.IsolatedAsyncioTestCase):
    """Test suite verifying STT provider interface, mock responses, and error handling."""

    async def asyncSetUp(self) -> None:
        self.mock_stt = MockSTTProvider(default_transcript="Open Notepad", confidence=0.95)
        self.sample_audio = AudioData(raw_data=b"\x00\x00" * 1600, sample_rate=16000)

    async def test_mock_stt_successful_transcription(self) -> None:
        """Verify successful transcription returns structured STTResult."""
        res = await self.mock_stt.transcribe(self.sample_audio)
        self.assertIsInstance(res, STTResult)
        self.assertEqual(res.transcript, "Open Notepad")
        self.assertEqual(res.confidence, 0.95)
        self.assertEqual(res.provider, "mock")
        self.assertEqual(self.mock_stt.transcribe_call_count, 1)

    async def test_mock_stt_custom_transcript_and_audio_tracking(self) -> None:
        """Verify updating transcript and audio inspection."""
        self.mock_stt.set_next_transcript("What is the time?", confidence=0.99)
        res = await self.mock_stt.transcribe(self.sample_audio)
        self.assertEqual(res.transcript, "What is the time?")
        self.assertIs(self.mock_stt.last_audio_received, self.sample_audio)

    async def test_mock_stt_empty_audio_raises_error(self) -> None:
        """Verify passing empty audio raises STTError."""
        empty_audio = AudioData(raw_data=b"")
        with self.assertRaises(STTError):
            await self.mock_stt.transcribe(empty_audio)

    async def test_mock_stt_simulated_failure(self) -> None:
        """Verify failure injection raises STTError."""
        self.mock_stt.simulate_failure = True
        with self.assertRaises(STTError):
            await self.mock_stt.transcribe(self.sample_audio)

    async def test_speech_recognition_provider_empty_audio_rejection(self) -> None:
        """Verify SpeechRecognitionSTTProvider rejects empty or truncated buffers."""
        sr_provider = SpeechRecognitionSTTProvider(timeout=1.0)
        with self.assertRaises(STTError):
            await sr_provider.transcribe(AudioData(raw_data=b""))


if __name__ == "__main__":
    unittest.main()
