"""Unit tests for BUDDY Voice Activity Detection (VAD)."""

import struct
import time
import unittest
from app.voice import (
    EnergyVAD,
    MockVAD,
    VADState,
)


class TestVoiceActivityDetection(unittest.TestCase):
    """Test suite verifying energy calculation and VAD state progression."""

    def setUp(self) -> None:
        self.vad = EnergyVAD(
            energy_threshold=300.0,
            silence_timeout=0.2,
            min_speech_duration=0.1,
            max_recording_duration=1.0,
        )

    def _generate_pcm_chunk(self, amplitude: int, samples: int = 512) -> bytes:
        """Helper generating constant amplitude 16-bit PCM chunk."""
        return struct.pack(f"<{samples}h", *([amplitude] * samples))

    def test_rms_calculation(self) -> None:
        """Verify RMS energy math on silent and active chunks."""
        silent_chunk = self._generate_pcm_chunk(amplitude=0)
        loud_chunk = self._generate_pcm_chunk(amplitude=1000)

        self.assertAlmostEqual(EnergyVAD.calculate_chunk_rms(silent_chunk), 0.0)
        self.assertAlmostEqual(EnergyVAD.calculate_chunk_rms(loud_chunk), 1000.0)

    def test_state_transition_progression(self) -> None:
        """Verify WAITING -> SPEAKING -> SILENCE -> COMPLETED flow."""
        self.assertEqual(self.vad.state, VADState.WAITING)

        silence_chunk = self._generate_pcm_chunk(amplitude=50)
        speech_chunk = self._generate_pcm_chunk(amplitude=2000)

        # 1. Silence while waiting stays WAITING
        st = self.vad.process_chunk(silence_chunk)
        self.assertEqual(st, VADState.WAITING)

        # 2. Loud chunk triggers SPEAKING
        st = self.vad.process_chunk(speech_chunk)
        self.assertEqual(st, VADState.SPEAKING)

        # Keep speaking for > min_speech_duration (0.1s)
        time.sleep(0.12)
        st = self.vad.process_chunk(speech_chunk)
        self.assertEqual(st, VADState.SPEAKING)

        # 3. Silence chunk transitions to SILENCE
        st = self.vad.process_chunk(silence_chunk)
        self.assertEqual(st, VADState.SILENCE)

        # 4. Wait for silence timeout (0.2s)
        time.sleep(0.25)
        st = self.vad.process_chunk(silence_chunk)
        self.assertEqual(st, VADState.COMPLETED)

    def test_max_recording_duration_forces_completion(self) -> None:
        """Verify exceeding max_recording_duration transitions to COMPLETED."""
        vad = EnergyVAD(energy_threshold=100.0, max_recording_duration=0.1)
        speech_chunk = self._generate_pcm_chunk(amplitude=2000)

        vad.process_chunk(speech_chunk)
        time.sleep(0.15)
        st = vad.process_chunk(speech_chunk)
        self.assertEqual(st, VADState.COMPLETED)

    def test_mock_vad(self) -> None:
        """Verify MockVAD returns predefined sequence and respects manual state injection."""
        transitions = [VADState.WAITING, VADState.SPEAKING, VADState.SILENCE, VADState.COMPLETED]
        mock = MockVAD(transitions)

        for expected in transitions:
            self.assertEqual(mock.process_chunk(b""), expected)

        mock.reset()
        self.assertEqual(mock.state, VADState.WAITING)

        mock.set_state(VADState.COMPLETED)
        self.assertEqual(mock.state, VADState.COMPLETED)


if __name__ == "__main__":
    unittest.main()
