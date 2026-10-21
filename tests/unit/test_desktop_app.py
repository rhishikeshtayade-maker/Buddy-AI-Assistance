"""Unit tests for BuddyDesktopApp orchestration and single-instance handling."""

from __future__ import annotations

import sys
import unittest
import uuid

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.desktop.app import BuddyDesktopApp
from app.desktop.single_instance import SingleInstanceGuard


class TestBuddyDesktopApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.qapp = QApplication.instance()
        if cls.qapp is None:
            cls.qapp = QApplication(sys.argv)

    def test_duplicate_instance_rejection_exits_zero(self) -> None:
        """When an instance is already running, a second BuddyDesktopApp exits cleanly with code 0."""
        shared_name = f"test-app-dup-{uuid.uuid4().hex[:8]}"
        primary_guard = SingleInstanceGuard(name=shared_name)
        self.assertTrue(primary_guard.acquire())

        try:
            duplicate_guard = SingleInstanceGuard(name=shared_name)
            app = BuddyDesktopApp(
                use_mock_voice=True,
                guard=duplicate_guard,
            )
            # app.run() should immediately reject the duplicate and return 0
            exit_code = app.run()
            self.assertEqual(exit_code, 0)
        finally:
            primary_guard.release()

    def test_app_lifecycle_startup_and_orderly_exit(self) -> None:
        """BuddyDesktopApp successfully starts runtime without self-collision and exits cleanly."""
        unique_name = f"test-app-run-{uuid.uuid4().hex[:8]}"
        guard = SingleInstanceGuard(name=unique_name)

        app = BuddyDesktopApp(
            use_mock_voice=True,
            start_in_tray=True,
            guard=guard,
        )

        # Schedule orderly exit after 400ms
        QTimer.singleShot(400, app.exit_application)

        exit_code = app.run()
        self.assertEqual(exit_code, 0)
        # Guard must be released after cleanup
        self.assertFalse(guard.acquired)
