"""BUDDY Desktop Settings Dialog.

Translucent preferences window allowing customization of animation intensity,
HUD opacity, screen position, audio sound cues, microphone state, and opt-in
login startup.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.desktop.settings import AnimationIntensity, DesktopSettings, HudPosition
from app.desktop.startup import LoginStartupManager
from app.desktop.ui.theme import Theme


class SettingsDialog(QDialog):
    """Fully opaque desktop preferences dialog."""

    def __init__(
        self,
        settings: DesktopSettings,
        parent: Optional[QWidget] = None,
        on_save: Optional[Callable[[DesktopSettings], None]] = None,
        startup_manager: Optional[LoginStartupManager] = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings.model_copy()
        self._on_save = on_save
        self._startup_mgr = startup_manager or LoginStartupManager()

        self.setWindowTitle("BUDDY — Preferences")
        self.setFixedWidth(460)

        # Explicitly ensure window is 100% opaque (never translucent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setWindowOpacity(1.0)

        # Independent window associated with BUDDY and elevated above on-top HUD
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowStaysOnTopHint
        )

        pal = self.palette()
        pal.setColor(self.backgroundRole(), Theme.BG_OPAQUE_BASE)
        self.setPalette(pal)

        self._setup_ui()

    def paintEvent(self, event) -> None:
        """Paint solid opaque background guaranteeing zero transparency bleed-through."""
        painter = QPainter(self)
        painter.fillRect(self.rect(), Theme.BG_OPAQUE_BASE)
        super().paintEvent(event)

    def center_on_screen(self) -> None:
        """Position dialog safely in the center of the available screen area to avoid HUD overlap."""
        screen = None
        if self.parentWidget() and self.parentWidget().window():
            screen = self.parentWidget().window().screen()
        if not screen:
            screen = QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            dlg_size = self.sizeHint()
            w = max(self.width(), dlg_size.width())
            h = max(self.height(), dlg_size.height())
            x = geo.x() + max(0, (geo.width() - w) // 2)
            y = geo.y() + max(0, (geo.height() - h) // 2)
            self.move(x, y)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.center_on_screen()

    def _setup_ui(self) -> None:
        self.setStyleSheet("""
            QDialog {
                background-color: #0e121b;
                color: #f5f8ff;
            }
            QFrame#SettingsCard {
                background-color: #161c2a;
                border: 1px solid #1e2638;
                border-radius: 12px;
            }
            QLabel {
                color: #f5f8ff;
                font-family: 'Segoe UI', sans-serif;
                font-size: 10pt;
                border: none;
                background: transparent;
            }
            QComboBox {
                background-color: #1e2638;
                border: 1px solid #2d3748;
                border-radius: 6px;
                padding: 6px 12px;
                color: #f5f8ff;
                font-size: 9pt;
            }
            QComboBox QAbstractItemView {
                background-color: #161c2a;
                color: #f5f8ff;
                selection-background-color: #00d2ff;
                selection-color: #000000;
                border: 1px solid #2d3748;
            }
            QComboBox::drop-down {
                border: none;
            }
            QSlider::groove:horizontal {
                height: 6px;
                background: #2d3748;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #00d2ff;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #ffffff;
                width: 16px;
                margin-top: -5px;
                margin-bottom: -5px;
                border-radius: 8px;
            }
            QCheckBox {
                color: #f5f8ff;
                font-size: 9.5pt;
                background: transparent;
                border: none;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid #4a5568;
                background: #1e2638;
            }
            QCheckBox::indicator:checked {
                background: #00d2ff;
                border: 1px solid #00d2ff;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(14, 14, 14, 14)

        # Solid container card
        self._card = QFrame()
        self._card.setObjectName("SettingsCard")

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(20, 20, 20, 20)
        card_layout.setSpacing(16)

        # Header
        header_layout = QHBoxLayout()
        title_label = QLabel("BUDDY Preferences")
        title_label.setFont(Theme.primary_font(13, bold=True))
        title_label.setStyleSheet("color: #00f5d4;")
        header_layout.addWidget(title_label)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet("""
            QPushButton {
                background: #1e2638;
                color: #f5f8ff;
                border-radius: 14px;
                font-size: 11pt;
                border: 1px solid #2d3748;
            }
            QPushButton:hover {
                background: #e53e3e;
                border: 1px solid #e53e3e;
            }
        """)
        close_btn.clicked.connect(self.reject)
        header_layout.addWidget(close_btn)
        card_layout.addLayout(header_layout)

        # Form layout
        form = QFormLayout()
        form.setSpacing(14)

        # 1. Animation Intensity
        self._intensity_combo = QComboBox()
        self._intensity_combo.addItem("Full (30 FPS, vibrant)", AnimationIntensity.FULL)
        self._intensity_combo.addItem("Reduced (12 FPS, low CPU)", AnimationIntensity.REDUCED)
        self._intensity_combo.addItem("Off (Static, reduced motion)", AnimationIntensity.OFF)
        idx = self._intensity_combo.findData(self._settings.animation_intensity)
        if idx >= 0:
            self._intensity_combo.setCurrentIndex(idx)
        form.addRow("Animations:", self._intensity_combo)

        # 2. HUD Opacity Slider
        opacity_layout = QHBoxLayout()
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(40, 100)
        self._opacity_slider.setValue(int(self._settings.hud_opacity * 100))
        self._opacity_val_label = QLabel(f"{int(self._settings.hud_opacity * 100)}%")
        self._opacity_slider.valueChanged.connect(lambda v: self._opacity_val_label.setText(f"{v}%"))
        opacity_layout.addWidget(self._opacity_slider)
        opacity_layout.addWidget(self._opacity_val_label)
        form.addRow("HUD Opacity:", opacity_layout)

        # 3. Position
        self._position_combo = QComboBox()
        self._position_combo.addItem("Bottom Right", HudPosition.BOTTOM_RIGHT)
        self._position_combo.addItem("Top Right", HudPosition.TOP_RIGHT)
        self._position_combo.addItem("Bottom Left", HudPosition.BOTTOM_LEFT)
        self._position_combo.addItem("Top Left", HudPosition.TOP_LEFT)
        self._position_combo.addItem("Top Center", HudPosition.TOP_CENTER)
        pos_idx = self._position_combo.findData(self._settings.hud_position)
        if pos_idx >= 0:
            self._position_combo.setCurrentIndex(pos_idx)
        form.addRow("HUD Anchor:", self._position_combo)

        # 4. Sound cues toggle
        self._sound_check = QCheckBox("Enable voice & sound output")
        self._sound_check.setChecked(self._settings.sound_enabled)
        form.addRow("Audio:", self._sound_check)

        # 5. Start at sign-in (explicit opt-in)
        self._startup_check = QCheckBox("Start BUDDY when I sign in to Windows")
        # Check actual registry state or saved setting
        actual_startup = self._startup_mgr.is_enabled()
        self._startup_check.setChecked(actual_startup)
        form.addRow("Startup:", self._startup_check)

        startup_note = QLabel("Requires explicit opt-in. Registers in Windows Task Manager Startup.")
        startup_note.setFont(Theme.primary_font(8))
        startup_note.setStyleSheet("color: #a5b2cd;")
        form.addRow("", startup_note)

        # 6. Force opaque toggle (fallback for systems without GPU compositing)
        self._opaque_check = QCheckBox("Force solid dark background (no translucency)")
        self._opaque_check.setChecked(self._settings.force_opaque)
        form.addRow("Fallback:", self._opaque_check)

        card_layout.addLayout(form)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: #1e2638;
                color: #f5f8ff;
                padding: 6px 16px;
                border-radius: 6px;
                border: 1px solid #2d3748;
            }
            QPushButton:hover {
                background: #2d3748;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("Save Preferences")
        save_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00d2ff, stop:1 #3a7bd5);
                color: #ffffff;
                font-weight: bold;
                padding: 6px 18px;
                border-radius: 6px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00f5d4, stop:1 #00d2ff);
            }
        """)
        save_btn.clicked.connect(self._handle_save)
        btn_layout.addWidget(save_btn)

        card_layout.addLayout(btn_layout)
        main_layout.addWidget(self._card)

    def _handle_save(self) -> None:
        self._settings.animation_intensity = self._intensity_combo.currentData()
        self._settings.hud_opacity = self._opacity_slider.value() / 100.0
        self._settings.hud_position = self._position_combo.currentData()
        self._settings.sound_enabled = self._sound_check.isChecked()
        self._settings.force_opaque = self._opaque_check.isChecked()

        # Handle startup registry update
        want_startup = self._startup_check.isChecked()
        self._settings.start_at_login = want_startup
        self._startup_mgr.apply(want_startup)

        if self._on_save:
            self._on_save(self._settings)

        self.accept()
