"""BUDDY Desktop Application Orchestrator.

Combines PySide6 GUI (Glass HUD, System Tray, Settings Dialog) with the
persistent background DesktopRuntime into a unified desktop companion.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from typing import Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.config import BuddyConfig
from app.desktop.bridge import UiUpdate
from app.desktop.runtime import DesktopRuntime
from app.desktop.settings import DesktopSettings, SettingsStore
from app.desktop.single_instance import SingleInstanceGuard
from app.desktop.startup import LoginStartupManager
from app.desktop.ui.hud import GlassHudWindow
from app.desktop.ui.settings_dialog import SettingsDialog
from app.desktop.ui.tray import BuddySystemTray

logger = logging.getLogger("buddy.desktop.app")


class ConfirmationBridge(QObject):
    """Bridge for prompting user approval on the GUI thread."""

    confirm_signal = Signal(str, object)  # (prompt_text, reply_holder_dict)

    def __init__(self) -> None:
        super().__init__()
        self.confirm_signal.connect(self._on_confirm_requested)

    def _on_confirm_requested(self, prompt: str, holder: dict) -> None:
        reply = QMessageBox.question(
            None,
            "BUDDY — Action Confirmation",
            f"BUDDY is requesting permission to:\n\n{prompt}\n\nDo you want to proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        holder["result"] = (reply == QMessageBox.StandardButton.Yes)
        holder["event"].set()


class BuddyDesktopApp:
    """Main desktop application lifecycle manager."""

    def __init__(
        self,
        config: Optional[BuddyConfig] = None,
        start_in_tray: bool = False,
        use_mock_voice: bool = False,
        guard: Optional[SingleInstanceGuard] = None,
    ) -> None:
        self._config = config or BuddyConfig.load_from_env()
        self._settings_store = SettingsStore()
        self._settings = self._settings_store.load()
        self._start_in_tray = start_in_tray or self._settings.start_minimized_to_tray
        self._use_mock_voice = use_mock_voice

        # Instance guard
        self._guard = guard or SingleInstanceGuard()

        # Qt Application
        self._qapp: Optional[QApplication] = None
        self._hud: Optional[GlassHudWindow] = None
        self._tray: Optional[BuddySystemTray] = None
        self._runtime: Optional[DesktopRuntime] = None
        self._confirm_bridge = ConfirmationBridge()

    def run(self) -> int:
        """Start desktop application."""
        # Check single instance
        if not self._guard.acquire():
            print("BUDDY is already running on this desktop. Exiting duplicate instance.", file=sys.stderr)
            return 0

        # Initialize Qt Application
        self._qapp = QApplication.instance()
        if self._qapp is None:
            self._qapp = QApplication(sys.argv)

        self._qapp.setApplicationName("BUDDY Assistant")
        self._qapp.setQuitOnLastWindowClosed(False)  # Crucial: minimizing/closing HUD keeps tray alive!

        # Initialize HUD Window
        self._hud = GlassHudWindow(self._settings)

        # Initialize System Tray
        self._tray = BuddySystemTray(
            on_toggle_show=self._handle_tray_toggle,
            on_pause_resume=self._handle_toggle_listening,
            on_open_settings=self._handle_open_settings,
            on_exit=self.exit_application,
        )
        self._tray.show()

        # Initialize Background Runtime
        self._runtime = DesktopRuntime(
            config=self._config,
            settings=self._settings,
            settings_store=self._settings_store,
            on_ui_update=self._hud.on_ui_update,
            confirm_callback=self._gui_confirm_callback,
            use_mock_voice=self._use_mock_voice,
            instance_guard=self._guard,
        )

        # Wire HUD signals
        self._hud.toggle_listening_requested.connect(self._handle_toggle_listening)
        self._hud.submit_text_requested.connect(self._handle_submit_text)
        self._hud.settings_requested.connect(self._handle_open_settings)
        self._hud.exit_requested.connect(self.exit_application)

        # Start runtime thread
        started = self._runtime.start_background()
        if not started:
            logger.error("Failed to start DesktopRuntime background thread.")
            self._guard.release()
            return 1

        # Setup OS signal handlers
        self._setup_signals()

        # Show HUD unless starting in tray
        if not self._start_in_tray:
            self._hud.show_hud()
            self._tray.set_hud_visible_state(True)
        else:
            self._tray.set_hud_visible_state(False)

        # Update initial tray icon based on pause state
        self._tray.set_paused_state(self._runtime.is_paused)

        # Enter Qt Event Loop
        exit_code = self._qapp.exec()

        # Orderly shutdown on loop exit
        self._cleanup()
        return exit_code

    def _gui_confirm_callback(self, prompt: str) -> bool:
        """Called from runtime thread to ask confirmation on GUI thread."""
        import threading
        holder = {"result": False, "event": threading.Event()}
        self._confirm_bridge.confirm_signal.emit(prompt, holder)
        # Bounded wait for user interaction (timeout 30s)
        holder["event"].wait(timeout=30.0)
        return holder["result"]

    def _handle_tray_toggle(self) -> None:
        if not self._hud:
            return
        if self._hud.isVisible() and self._hud.windowOpacity() > 0.1:
            self._hud.hide_hud()
            if self._tray:
                self._tray.set_hud_visible_state(False)
        else:
            self._hud.show_hud()
            if self._tray:
                self._tray.set_hud_visible_state(True)

    def _handle_toggle_listening(self) -> None:
        if not self._runtime:
            return
        if self._runtime.is_paused:
            self._runtime.resume_listening(reason="User clicked listening toggle")
            if self._tray:
                self._tray.set_paused_state(False)
        else:
            self._runtime.pause_listening(reason="User clicked listening toggle")
            if self._tray:
                self._tray.set_paused_state(True)

    def _handle_submit_text(self, text: str) -> None:
        if self._runtime:
            self._runtime.submit_user_text(text)

    def _handle_open_settings(self) -> None:
        if not self._hud:
            return
        dialog = SettingsDialog(
            settings=self._settings,
            parent=self._hud,
            on_save=self._on_settings_saved,
        )
        dialog.exec()

    def _on_settings_saved(self, new_settings: DesktopSettings) -> None:
        self._settings = new_settings
        self._settings_store.save(new_settings)
        if self._hud:
            self._hud.update_settings(new_settings)
        if self._runtime:
            self._runtime.update_settings(new_settings)

    def _setup_signals(self) -> None:
        try:
            signal.signal(signal.SIGINT, lambda s, f: self.exit_application())
            signal.signal(signal.SIGTERM, lambda s, f: self.exit_application())
        except (ValueError, AttributeError):
            pass

    def exit_application(self) -> None:
        """Trigger orderly shutdown and terminate application."""
        logger.info("Initiating BUDDY desktop application orderly exit...")
        self._cleanup()
        if self._qapp:
            self._qapp.quit()

    def _cleanup(self) -> None:
        if self._runtime and self._runtime.is_running:
            self._runtime.stop_and_join(timeout=5.0)
        if self._tray:
            self._tray.hide()
        self._guard.release()


def main(args: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="BUDDY — Persistent Desktop Assistant")
    parser.add_argument("--tray", action="store_true", help="Start minimized to the system tray")
    parser.add_argument("--mock", action="store_true", help="Run with mock voice pipeline")
    parsed = parser.parse_args(args)

    app = BuddyDesktopApp(start_in_tray=parsed.tray, use_mock_voice=parsed.mock)
    return app.run()


if __name__ == "__main__":
    sys.exit(main())
