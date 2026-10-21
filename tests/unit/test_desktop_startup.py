"""Unit tests for BUDDY Login Startup Manager."""

import unittest
from pathlib import Path

from app.desktop.startup import (
    InMemoryRunKeyBackend,
    LoginStartupManager,
    RUN_VALUE_NAME,
    build_launch_command,
)


class TestLoginStartupManager(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = InMemoryRunKeyBackend()
        self.mgr = LoginStartupManager(
            backend=self.backend,
            command='"C:\\test\\pythonw.exe" "D:\\BUDDY\\app\\desktop\\__main__.py" --tray',
        )

    def test_startup_disabled_by_default(self) -> None:
        self.assertFalse(self.mgr.is_enabled())
        self.assertIsNone(self.backend.read(RUN_VALUE_NAME))

    def test_explicit_enable_and_disable(self) -> None:
        # User explicitly opts in
        self.assertTrue(self.mgr.enable())
        self.assertTrue(self.mgr.is_enabled())
        self.assertIn("--tray", self.backend.read(RUN_VALUE_NAME))

        # User opts out
        self.assertTrue(self.mgr.disable())
        self.assertFalse(self.mgr.is_enabled())
        self.assertIsNone(self.backend.read(RUN_VALUE_NAME))

    def test_apply_setting(self) -> None:
        self.mgr.apply(True)
        self.assertTrue(self.mgr.is_enabled())

        self.mgr.apply(False)
        self.assertFalse(self.mgr.is_enabled())

    def test_build_launch_command(self) -> None:
        cmd = build_launch_command(interpreter=Path("C:/Python313/pythonw.exe"), project_root=Path("D:/BUDDY"))
        self.assertIn("pythonw.exe", cmd)
        self.assertIn("app\\desktop\\__main__.py", cmd)
        self.assertIn("--tray", cmd)
