"""Unit tests for BUDDY System and Telemetry Tools."""

from __future__ import annotations

import unittest

from app.tools.system import (
    SystemBatteryTool,
    SystemGetVolumeTool,
    SystemInfoTool,
    SystemSetVolumeTool,
)


class TestSystemTools(unittest.IsolatedAsyncioTestCase):
    """Test execution and verification of system query tools."""

    async def test_system_info_tool(self) -> None:
        tool = SystemInfoTool()
        self.assertEqual(tool.definition.name, "system.get_info")

        output = await tool.execute({})
        self.assertIn("os", output)
        self.assertIn("python_version", output)
        self.assertIn("cpu_count_logical", output)
        self.assertIn("memory_total_gb", output)

        verified = await tool.verify({}, output)
        self.assertTrue(verified)

    async def test_system_battery_tool(self) -> None:
        tool = SystemBatteryTool()
        self.assertEqual(tool.definition.name, "system.get_battery")

        output = await tool.execute({})
        self.assertIn("has_battery", output)
        self.assertIn("percent", output)

        verified = await tool.verify({}, output)
        self.assertTrue(verified)

    async def test_volume_get_and_set_tool(self) -> None:
        get_tool = SystemGetVolumeTool()
        set_tool = SystemSetVolumeTool()

        # Set volume to 75
        validated_args = await set_tool.validate_input({"level": 75})
        set_output = await set_tool.execute(validated_args)
        verified = await set_tool.verify(validated_args, set_output)
        self.assertTrue(verified)

        # Query volume
        get_output = await get_tool.execute({})
        self.assertEqual(get_output["volume"], 75)
        get_verified = await get_tool.verify({}, get_output)
        self.assertTrue(get_verified)

    async def test_volume_set_invalid_range_rejected(self) -> None:
        set_tool = SystemSetVolumeTool()
        with self.assertRaises(ValueError):
            await set_tool.validate_input({"level": 150})
        with self.assertRaises(ValueError):
            await set_tool.validate_input({"level": -10})
        with self.assertRaises(ValueError):
            await set_tool.validate_input({"level": "invalid"})


if __name__ == "__main__":
    unittest.main()
