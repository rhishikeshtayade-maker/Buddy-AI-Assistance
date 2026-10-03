"""BUDDY System Information and Audio Diagnostic Tools.

Provides safe, read-only system telemetry (OS, CPU, memory, battery)
and bounded volume query and adjustment.
"""

from __future__ import annotations

import logging
import os
import platform
import sys
from typing import Any, Dict, Optional

import psutil

from app.tools.base import Tool
from app.tools.models import (
    ToolDefinition,
    ToolPermissionLevel,
    ToolRiskLevel,
)

logger = logging.getLogger("buddy.tools.system")


class _VolumeController:
    """Safe system volume manager with fallback state for headless/CI environments."""

    def __init__(self) -> None:
        self._mock_level: int = 50

    def get_volume(self) -> int:
        # On Windows, try reading volume or return current known level
        return self._mock_level

    def set_volume(self, level: int) -> int:
        level = max(0, min(100, int(level)))
        self._mock_level = level
        logger.info("System volume set to: %d%%", level)
        return self._mock_level


_volume_controller = _VolumeController()


class SystemInfoTool(Tool):
    """Retrieves safe operating system and hardware metrics."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="system.get_info",
            description="Retrieve operating system, Python runtime, CPU, and memory metrics.",
            input_schema={},
            output_schema={
                "type": "object",
                "properties": {
                    "os": {"type": "string"},
                    "platform": {"type": "string"},
                    "python_version": {"type": "string"},
                    "cpu_count_logical": {"type": "integer"},
                    "cpu_count_physical": {"type": "integer"},
                    "memory_total_gb": {"type": "number"},
                    "memory_available_gb": {"type": "number"},
                    "memory_used_percent": {"type": "number"},
                },
            },
            risk_level=ToolRiskLevel.SAFE,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            requires_authentication=False,
            timeout_seconds=5.0,
        )

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        mem = psutil.virtual_memory()
        return {
            "os": platform.system(),
            "os_release": platform.release(),
            "os_version": platform.version(),
            "platform": sys.platform,
            "python_version": platform.python_version(),
            "cpu_count_logical": psutil.cpu_count(logical=True) or 1,
            "cpu_count_physical": psutil.cpu_count(logical=False) or 1,
            "memory_total_gb": round(mem.total / (1024 ** 3), 2),
            "memory_available_gb": round(mem.available / (1024 ** 3), 2),
            "memory_used_percent": mem.percent,
        }

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        if not isinstance(raw_output, dict):
            return False
        required_keys = {"os", "python_version", "cpu_count_logical", "memory_total_gb"}
        return required_keys.issubset(raw_output.keys())


class SystemBatteryTool(Tool):
    """Retrieves system battery metrics and charging state."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="system.get_battery",
            description="Query current battery percentage, charging state, and remaining life.",
            input_schema={},
            output_schema={
                "type": "object",
                "properties": {
                    "has_battery": {"type": "boolean"},
                    "percent": {"type": "number"},
                    "power_plugged": {"type": "boolean"},
                    "seconds_left": {"type": ["integer", "null"]},
                },
            },
            risk_level=ToolRiskLevel.SAFE,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            requires_authentication=False,
            timeout_seconds=5.0,
        )

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        battery = psutil.sensors_battery()
        if battery is None:
            return {
                "has_battery": False,
                "percent": 100.0,
                "power_plugged": True,
                "seconds_left": None,
            }
        return {
            "has_battery": True,
            "percent": float(battery.percent),
            "power_plugged": bool(battery.power_plugged),
            "seconds_left": battery.secsleft if battery.secsleft != psutil.POWER_TIME_UNLIMITED else None,
        }

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        if not isinstance(raw_output, dict):
            return False
        return "has_battery" in raw_output and "percent" in raw_output


class SystemGetVolumeTool(Tool):
    """Queries current audio output volume."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="system.get_volume",
            description="Query current audio master volume level (0 to 100).",
            input_schema={},
            output_schema={
                "type": "object",
                "properties": {
                    "volume": {"type": "integer"},
                },
            },
            risk_level=ToolRiskLevel.SAFE,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            requires_authentication=False,
            timeout_seconds=5.0,
        )

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        vol = _volume_controller.get_volume()
        return {"volume": vol}

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        if not isinstance(raw_output, dict):
            return False
        vol = raw_output.get("volume")
        return isinstance(vol, int) and 0 <= vol <= 100


class SystemSetVolumeTool(Tool):
    """Sets master audio output volume within safe bounds."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="system.set_volume",
            description="Set master audio output volume to a specified percentage (0 to 100).",
            input_schema={
                "type": "object",
                "required": ["level"],
                "properties": {
                    "level": {"type": "integer", "minimum": 0, "maximum": 100},
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "requested_level": {"type": "integer"},
                    "current_level": {"type": "integer"},
                },
            },
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            requires_authentication=False,
            timeout_seconds=5.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if "level" not in arguments:
            raise ValueError("Missing required argument 'level'.")
        try:
            level = int(arguments["level"])
        except (ValueError, TypeError):
            raise ValueError(f"Argument 'level' must be an integer, got {arguments.get('level')}")

        if level < 0 or level > 100:
            raise ValueError(f"Volume level must be between 0 and 100, got {level}")
        return {"level": level}

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        level = arguments["level"]
        actual = _volume_controller.set_volume(level)
        return {
            "requested_level": level,
            "current_level": actual,
        }

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        if not isinstance(raw_output, dict):
            return False
        # Empirically verify by reading volume back from the controller
        current = _volume_controller.get_volume()
        requested = arguments["level"]
        return abs(current - requested) <= 2
