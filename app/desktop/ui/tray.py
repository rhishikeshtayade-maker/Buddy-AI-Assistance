"""BUDDY System Tray Icon and Context Menu.

Provides background presence, quick toggles (Show/Hide, Pause/Resume Listening),
Settings access, and clean exit.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget


def create_tray_icon(active: bool = True, paused: bool = False) -> QIcon:
    """Procedurally create a crisp, high-DPI system tray icon."""
    size = 64
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    center = QPointF(size / 2.0, size / 2.0)
    radius = size * 0.42

    if paused:
        c1 = QColor(255, 183, 3)
        c2 = QColor(108, 117, 125)
    elif active:
        c1 = QColor(0, 245, 212)
        c2 = QColor(58, 123, 213)
    else:
        c1 = QColor(0, 210, 255)
        c2 = QColor(157, 80, 187)

    # Glowing outer ring
    grad = QRadialGradient(center, radius)
    grad.setColorAt(0.0, QColor(255, 255, 255, 230))
    grad.setColorAt(0.5, c1)
    grad.setColorAt(1.0, c2)

    painter.setBrush(QBrush(grad))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(center, radius, radius)

    # Inner core
    painter.setBrush(QBrush(QColor(14, 18, 27, 200)))
    painter.drawEllipse(center, radius * 0.55, radius * 0.55)

    # Accent center pip
    pip_color = QColor(255, 183, 3) if paused else QColor(0, 245, 212)
    painter.setBrush(QBrush(pip_color))
    painter.drawEllipse(center, radius * 0.22, radius * 0.22)

    painter.end()
    return QIcon(pixmap)


class BuddySystemTray(QSystemTrayIcon):
    """System tray integration for persistent desktop assistant."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        on_toggle_show: Optional[Callable[[], None]] = None,
        on_pause_resume: Optional[Callable[[], None]] = None,
        on_open_settings: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(create_tray_icon(active=True, paused=False), parent)

        self._on_toggle_show = on_toggle_show
        self._on_pause_resume = on_pause_resume
        self._on_open_settings = on_open_settings
        self._on_exit = on_exit

        self._is_paused = False
        self._is_hud_visible = True

        self._setup_menu()
        self.activated.connect(self._on_tray_activated)
        self.setToolTip("BUDDY — Your Voice. Your Laptop. Your Control.")

    def _setup_menu(self) -> None:
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #141a27;
                border: 1px solid rgba(0, 210, 255, 60);
                border-radius: 8px;
                padding: 6px;
                color: #f5f8ff;
                font-family: 'Segoe UI', sans-serif;
                font-size: 10pt;
            }
            QMenu::item {
                padding: 6px 20px 6px 10px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: rgba(0, 210, 255, 45);
                color: #00f5d4;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(255, 255, 255, 20);
                margin: 4px 6px;
            }
        """)

        # 1. Show / Hide BUDDY
        self._show_action = QAction("Hide BUDDY", self)
        self._show_action.triggered.connect(self._handle_toggle_show)
        menu.addAction(self._show_action)

        menu.addSeparator()

        # 2. Pause / Resume Listening
        self._pause_action = QAction("Pause Listening", self)
        self._pause_action.triggered.connect(self._handle_pause_resume)
        menu.addAction(self._pause_action)

        # 3. Settings
        self._settings_action = QAction("Settings...", self)
        if self._on_open_settings:
            self._settings_action.triggered.connect(self._on_open_settings)
        menu.addAction(self._settings_action)

        menu.addSeparator()

        # 4. Exit BUDDY
        self._exit_action = QAction("Exit BUDDY", self)
        if self._on_exit:
            self._exit_action.triggered.connect(self._on_exit)
        menu.addAction(self._exit_action)

        self.setContextMenu(menu)

    def set_paused_state(self, paused: bool) -> None:
        self._is_paused = paused
        self._pause_action.setText("Resume Listening" if paused else "Pause Listening")
        self.setIcon(create_tray_icon(active=not paused, paused=paused))
        tooltip = "BUDDY — Listening Paused" if paused else "BUDDY — Listening for 'Hey BUDDY'"
        self.setToolTip(tooltip)

    def set_hud_visible_state(self, visible: bool) -> None:
        self._is_hud_visible = visible
        self._show_action.setText("Hide BUDDY" if visible else "Show BUDDY")

    def _handle_toggle_show(self) -> None:
        if self._on_toggle_show:
            self._on_toggle_show()

    def _handle_pause_resume(self) -> None:
        if self._on_pause_resume:
            self._on_pause_resume()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._handle_toggle_show()
