"""Unit tests for BUDDY Audio Device Management."""

import unittest
from unittest.mock import MagicMock, patch

from app.voice import (
    AudioDevice,
    AudioDeviceError,
    AudioDeviceManager,
)


class TestAudioDeviceManager(unittest.TestCase):
    """Test suite verifying audio device enumeration, default detection, and validation."""

    def setUp(self) -> None:
        self.device_mgr = AudioDeviceManager()

    def test_list_devices_empty_or_available(self) -> None:
        """Verify device listing returns AudioDevice instances."""
        all_devs = self.device_mgr.list_all_devices()
        self.assertIsInstance(all_devs, list)
        for dev in all_devs:
            self.assertIsInstance(dev, AudioDevice)
            self.assertIsInstance(dev.name, str)

    def test_list_input_and_output_devices_filtered(self) -> None:
        """Verify input devices have is_input=True and output devices have is_output=True."""
        inputs = self.device_mgr.list_input_devices()
        outputs = self.device_mgr.list_output_devices()

        for d in inputs:
            self.assertTrue(d.is_input)
            self.assertGreater(d.max_input_channels, 0)

        for d in outputs:
            self.assertTrue(d.is_output)
            self.assertGreater(d.max_output_channels, 0)

    @patch("sounddevice.query_devices")
    @patch("sounddevice.default")
    def test_mocked_devices_selection(self, mock_default, mock_query) -> None:
        """Verify selection logic with controlled mock hardware list."""
        mock_query.return_value = [
            {"name": "Mock Mic Array", "max_input_channels": 2, "max_output_channels": 0, "default_samplerate": 16000.0},
            {"name": "Mock Speakers", "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000.0},
        ]
        mock_default.device = (0, 1)

        mgr = AudioDeviceManager()
        in_dev = mgr.validate_input_device("default")
        self.assertEqual(in_dev.name, "Mock Mic Array")
        self.assertEqual(in_dev.device_id, 0)

        out_dev = mgr.validate_output_device("default")
        self.assertEqual(out_dev.name, "Mock Speakers")
        self.assertEqual(out_dev.device_id, 1)

        # Select by name substring
        selected_in = mgr.select_input_device("Mic Array")
        self.assertEqual(selected_in.device_id, 0)

        selected_out = mgr.select_output_device("Speakers")
        self.assertEqual(selected_out.device_id, 1)

    def test_invalid_device_raises_error(self) -> None:
        """Verify querying non-existent device raises AudioDeviceError."""
        with self.assertRaises(AudioDeviceError):
            self.device_mgr.validate_input_device(99999)

        with self.assertRaises(AudioDeviceError):
            self.device_mgr.validate_input_device("NonExistentMicrophone12345")


if __name__ == "__main__":
    unittest.main()
