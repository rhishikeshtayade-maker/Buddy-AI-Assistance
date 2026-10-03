"""Unit tests for BUDDY Application Management Tools."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.tools.applications import (
    APPROVED_APPLICATIONS,
    AppCloseTool,
    AppListTool,
    AppOpenTool,
)


class TestAppTools(unittest.IsolatedAsyncioTestCase):
    """Test allowlist enforcement and process lifecycle operations."""

    async def test_app_list_tool(self) -> None:
        tool = AppListTool()
        output = await tool.execute({})
        self.assertIn("applications", output)
        self.assertIn("count", output)
        self.assertTrue(await tool.verify({}, output))

    async def test_app_open_rejects_unapproved_application(self) -> None:
        tool = AppOpenTool()
        unapproved = ["powershell", "cmd", "malware.exe", "curl", "format C:"]
        for app in unapproved:
            with self.assertRaises(ValueError):
                await tool.validate_input({"application": app})

    async def test_app_open_validates_approved_app(self) -> None:
        tool = AppOpenTool()
        for app in APPROVED_APPLICATIONS.keys():
            validated = await tool.validate_input({"application": app})
            self.assertEqual(validated["application"], app)

    @patch("subprocess.Popen")
    @patch("app.tools.applications._resolve_binary", return_value="C:\\Windows\\notepad.exe")
    async def test_app_open_execution_and_verify(self, mock_resolve: MagicMock, mock_popen: MagicMock) -> None:
        tool = AppOpenTool()
        output = await tool.execute({"application": "notepad"})

        mock_popen.assert_called_once_with(["C:\\Windows\\notepad.exe"], close_fds=True)
        self.assertTrue(output["launched"])

        # Test verification mock
        with patch("psutil.process_iter") as mock_iter:
            mock_proc = MagicMock()
            mock_proc.info = {"name": "notepad.exe"}
            mock_iter.return_value = [mock_proc]
            verified = await tool.verify({"application": "notepad"}, output)
            self.assertTrue(verified)

    async def test_app_close_rejects_unapproved_application(self) -> None:
        tool = AppCloseTool()
        with self.assertRaises(ValueError):
            await tool.validate_input({"application": "explorer_evil"})


if __name__ == "__main__":
    unittest.main()
