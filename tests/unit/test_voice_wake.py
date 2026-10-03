"""Unit tests for BUDDY Wake Word Detection Subsystem."""

import unittest
from app.voice import (
    AudioData,
    KeywordWakeWordDetector,
    MockSTTProvider,
    MockWakeWordDetector,
)


class TestWakeWordDetection(unittest.IsolatedAsyncioTestCase):
    """Test suite verifying wake word detection protocols and implementations."""

    async def asyncSetUp(self) -> None:
        self.sample_audio = AudioData(raw_data=b"\x00\x00" * 1600, sample_rate=16000)

    async def test_mock_wake_word_detector(self) -> None:
        """Verify MockWakeWordDetector returns configured boolean results."""
        detector = MockWakeWordDetector(wake_word="hey buddy", default_result=True)
        self.assertEqual(detector.wake_word, "hey buddy")

        res1 = await detector.detect(self.sample_audio)
        self.assertTrue(res1)
        self.assertEqual(detector.detect_call_count, 1)

        detector.set_result(False)
        res2 = await detector.detect(self.sample_audio)
        self.assertFalse(res2)

    async def test_keyword_wake_word_detector_success_and_failure(self) -> None:
        """Verify KeywordWakeWordDetector detects keyword presence via STT."""
        mock_stt = MockSTTProvider()
        detector = KeywordWakeWordDetector(stt_provider=mock_stt, wake_word="hey buddy")

        # Test case: keyword present
        mock_stt.set_next_transcript("Hey BUDDY, open Chrome")
        is_wake = await detector.detect(self.sample_audio)
        self.assertTrue(is_wake)

        # Test case: keyword absent
        mock_stt.set_next_transcript("What is the weather outside?")
        is_wake = await detector.detect(self.sample_audio)
        self.assertFalse(is_wake)

        # Test case: empty audio returns False
        empty_audio = AudioData(raw_data=b"")
        self.assertFalse(await detector.detect(empty_audio))


if __name__ == "__main__":
    unittest.main()
