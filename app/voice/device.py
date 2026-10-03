"""BUDDY Audio Device Management.

Provides device discovery, default selection, device validation,
and graceful handling of audio hardware disconnections or failures.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Union

from app.voice.exceptions import AudioDeviceError
from app.voice.models import AudioDevice

logger = logging.getLogger("buddy.voice.device")


class AudioDeviceManager:
    """Manages audio endpoint discovery, validation, and selection."""

    def __init__(self) -> None:
        self._selected_input: Optional[Union[int, str]] = None
        self._selected_output: Optional[Union[int, str]] = None

    def _query_devices_raw(self) -> list[dict]:
        """Safely query system devices via sounddevice if available."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            if isinstance(devices, dict):
                return [devices]
            return list(devices)
        except Exception as e:
            logger.warning("Could not query host audio devices: %s", e)
            return []

    def list_all_devices(self) -> List[AudioDevice]:
        """Return list of all recognized audio endpoints."""
        raw_devices = self._query_devices_raw()
        devices: List[AudioDevice] = []

        for idx, dev in enumerate(raw_devices):
            try:
                device = AudioDevice(
                    device_id=idx,
                    name=str(dev.get("name", f"Device {idx}")),
                    max_input_channels=int(dev.get("max_input_channels", 0)),
                    max_output_channels=int(dev.get("max_output_channels", 0)),
                    default_sample_rate=float(dev.get("default_samplerate", 16000.0)),
                    is_input=int(dev.get("max_input_channels", 0)) > 0,
                    is_output=int(dev.get("max_output_channels", 0)) > 0,
                    hostapi_name=str(dev.get("hostapi", "")),
                )
                devices.append(device)
            except Exception as parse_err:
                logger.debug("Failed parsing device at index %d: %s", idx, parse_err)

        return devices

    def list_input_devices(self) -> List[AudioDevice]:
        """Return all available audio input endpoints (microphones)."""
        return [d for d in self.list_all_devices() if d.is_input]

    def list_output_devices(self) -> List[AudioDevice]:
        """Return all available audio output endpoints (speakers/headphones)."""
        return [d for d in self.list_all_devices() if d.is_output]

    def get_default_input_device(self) -> Optional[AudioDevice]:
        """Detect system default microphone."""
        try:
            import sounddevice as sd
            default_in, _ = sd.default.device
            inputs = self.list_input_devices()
            for dev in inputs:
                if dev.device_id == default_in:
                    return dev
            return inputs[0] if inputs else None
        except Exception as e:
            logger.warning("Default input query failed: %s", e)
            inputs = self.list_input_devices()
            return inputs[0] if inputs else None

    def get_default_output_device(self) -> Optional[AudioDevice]:
        """Detect system default speaker/output."""
        try:
            import sounddevice as sd
            _, default_out = sd.default.device
            outputs = self.list_output_devices()
            for dev in outputs:
                if dev.device_id == default_out:
                    return dev
            return outputs[0] if outputs else None
        except Exception as e:
            logger.warning("Default output query failed: %s", e)
            outputs = self.list_output_devices()
            return outputs[0] if outputs else None

    def validate_input_device(self, identifier: Union[int, str]) -> AudioDevice:
        """Verify that an input device exists and has recording capability.

        Raises AudioDeviceError if invalid or unavailable.
        """
        if str(identifier).lower() == "default":
            dev = self.get_default_input_device()
            if not dev:
                raise AudioDeviceError("No default microphone available on host system.", device_name="default")
            return dev

        inputs = self.list_input_devices()
        if isinstance(identifier, int):
            for d in inputs:
                if d.device_id == identifier:
                    return d
            raise AudioDeviceError(f"Audio input device ID {identifier} not found.", device_name=str(identifier))

        # String name match (case-insensitive substring)
        norm_name = identifier.strip().lower()
        for d in inputs:
            if norm_name in d.name.lower():
                return d

        raise AudioDeviceError(f"Audio input device '{identifier}' not found or has no input channels.", device_name=identifier)

    def validate_output_device(self, identifier: Union[int, str]) -> AudioDevice:
        """Verify that an output device exists and has playback capability.

        Raises AudioDeviceError if invalid or unavailable.
        """
        if str(identifier).lower() == "default":
            dev = self.get_default_output_device()
            if not dev:
                raise AudioDeviceError("No default speaker available on host system.", device_name="default")
            return dev

        outputs = self.list_output_devices()
        if isinstance(identifier, int):
            for d in outputs:
                if d.device_id == identifier:
                    return d
            raise AudioDeviceError(f"Audio output device ID {identifier} not found.", device_name=str(identifier))

        # String name match (case-insensitive substring)
        norm_name = identifier.strip().lower()
        for d in outputs:
            if norm_name in d.name.lower():
                return d

        raise AudioDeviceError(f"Audio output device '{identifier}' not found or has no output channels.", device_name=identifier)

    def select_input_device(self, identifier: Union[int, str]) -> AudioDevice:
        """Select and store the active input device identifier."""
        validated = self.validate_input_device(identifier)
        self._selected_input = identifier
        logger.info("Selected audio input device: %s (ID=%d)", validated.name, validated.device_id)
        return validated

    def select_output_device(self, identifier: Union[int, str]) -> AudioDevice:
        """Select and store the active output device identifier."""
        validated = self.validate_output_device(identifier)
        self._selected_output = identifier
        logger.info("Selected audio output device: %s (ID=%d)", validated.name, validated.device_id)
        return validated
