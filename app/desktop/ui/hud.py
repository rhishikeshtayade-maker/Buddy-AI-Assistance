"""BUDDY Animated Glass HUD Window.

Floating translucent desktop interface built with PySide6, featuring
glassmorphism styling, soft cyan/blue/purple accent glow, responsive layout,
and real-time state synchronization.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.desktop.bridge import UiUpdate, VisualState
from app.desktop.settings import AnimationIntensity, DesktopSettings, HudPosition
from app.desktop.ui.orb import AnimatedOrbWidget
from app.desktop.ui.theme import PALETTES, Theme
from app.desktop.ui.waveform import WaveformWidget


class GlassHudWindow(QWidget):
    """Floating Glassmorphism Desktop HUD."""

    # Qt signals for thread-safe UI updates
    update_received = Signal(object)
    toggle_listening_requested = Signal()
    submit_text_requested = Signal(str)
    settings_requested = Signal()
    exit_requested = Signal()

    def __init__(
        self,
        settings: DesktopSettings,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._is_expanded = settings.expanded_mode
        self._drag_pos: Optional[QPoint] = None

        # Current state snapshot
        self._current_update: Optional[UiUpdate] = None
        self._visual_state = VisualState.STARTING

        # Window styling & flags
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        self._setup_ui()
        self._setup_animations()
        self.reposition(self._settings.hud_position)

        # Wire internal signal
        self.update_received.connect(self._apply_ui_update)

    def _setup_ui(self) -> None:
        self.setObjectName("GlassHudWindow")
        self.setMinimumWidth(340)

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(10, 10, 10, 10)
        self._main_layout.setSpacing(0)

        # Main glass panel container
        self._panel = QFrame(self)
        self._panel_layout = QVBoxLayout(self._panel)
        self._panel_layout.setContentsMargins(14, 12, 14, 12)
        self._panel_layout.setSpacing(8)

        # 1. Header: Brand, State/Mic Chip, Window Controls
        self._header_layout = QHBoxLayout()
        self._header_layout.setSpacing(8)

        # Brand
        self._brand_label = QLabel("BUDDY")
        self._brand_label.setFont(Theme.primary_font(11, bold=True))
        self._brand_label.setStyleSheet("color: #00f5d4; background: transparent;")
        self._header_layout.addWidget(self._brand_label)

        # State badge / mic button
        self._mic_chip = QPushButton("READY")
        self._mic_chip.setFont(Theme.primary_font(8, bold=True))
        self._mic_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mic_chip.setToolTip("Click to Pause or Resume Listening")
        self._mic_chip.clicked.connect(self.toggle_listening_requested.emit)
        self._update_chip_style(VisualState.STARTING)
        self._header_layout.addWidget(self._mic_chip)

        self._header_layout.addStretch()

        # Expand / Collapse button
        self._expand_btn = QPushButton("▲" if not self._is_expanded else "▼")
        self._expand_btn.setFixedSize(24, 24)
        self._expand_btn.setToolTip("Toggle Conversation Mode")
        self._expand_btn.clicked.connect(self.toggle_expanded_mode)
        self._style_header_btn(self._expand_btn)
        self._header_layout.addWidget(self._expand_btn)

        # Settings button
        self._settings_btn = QPushButton("⚙")
        self._settings_btn.setFixedSize(24, 24)
        self._settings_btn.setToolTip("Preferences")
        self._settings_btn.clicked.connect(self.settings_requested.emit)
        self._style_header_btn(self._settings_btn)
        self._header_layout.addWidget(self._settings_btn)

        # Close / Hide button
        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setToolTip("Hide to Tray")
        self._close_btn.clicked.connect(self.hide_hud)
        self._style_header_btn(self._close_btn, is_close=True)
        self._header_layout.addWidget(self._close_btn)

        self._panel_layout.addLayout(self._header_layout)

        # 2. Central AI Orb & Waveform layout
        self._center_layout = QHBoxLayout()
        self._center_layout.setContentsMargins(4, 2, 4, 2)
        self._center_layout.setSpacing(12)

        self._orb = AnimatedOrbWidget(self, intensity=self._settings.animation_intensity)
        self._center_layout.addWidget(self._orb)

        self._status_container = QVBoxLayout()
        self._status_container.setSpacing(4)
        self._status_container.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Status text
        self._status_label = QLabel("Initializing BUDDY...")
        self._status_label.setFont(Theme.primary_font(10))
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color: #f5f8ff; background: transparent;")
        self._status_container.addWidget(self._status_label)

        # Audio-reactive waveform
        self._waveform = WaveformWidget(self, intensity=self._settings.animation_intensity)
        self._status_container.addWidget(self._waveform)

        self._center_layout.addLayout(self._status_container)
        self._panel_layout.addLayout(self._center_layout)

        # 3. Expanded Conversation Container
        self._expanded_widget = QWidget(self)
        self._expanded_layout = QVBoxLayout(self._expanded_widget)
        self._expanded_layout.setContentsMargins(0, 6, 0, 0)
        self._expanded_layout.setSpacing(6)

        # Transcript box
        self._transcript_card = QFrame(self._expanded_widget)
        self._transcript_card.setStyleSheet("""
            QFrame {
                background: rgba(10, 14, 22, 180);
                border: 1px solid rgba(255, 255, 255, 25);
                border-radius: 8px;
                padding: 6px;
            }
        """)
        trans_layout = QVBoxLayout(self._transcript_card)
        trans_layout.setContentsMargins(8, 6, 8, 6)
        trans_layout.setSpacing(4)

        self._user_label = QLabel("")
        self._user_label.setFont(Theme.primary_font(9))
        self._user_label.setStyleSheet("color: #00d2ff; background: transparent;")
        self._user_label.setWordWrap(True)
        trans_layout.addWidget(self._user_label)

        self._ai_label = QLabel("")
        self._ai_label.setFont(Theme.primary_font(9))
        self._ai_label.setStyleSheet("color: #e2e8f0; background: transparent;")
        self._ai_label.setWordWrap(True)
        trans_layout.addWidget(self._ai_label)

        self._expanded_layout.addWidget(self._transcript_card)

        # Keyboard prompt input
        input_layout = QHBoxLayout()
        input_layout.setSpacing(6)

        self._input_field = QLineEdit()
        self._input_field.setPlaceholderText("Type a command or question...")
        self._input_field.setFont(Theme.primary_font(9))
        self._input_field.setStyleSheet("""
            QLineEdit {
                background: rgba(18, 24, 38, 220);
                border: 1px solid rgba(0, 210, 255, 60);
                border-radius: 6px;
                padding: 6px 10px;
                color: #ffffff;
            }
            QLineEdit:focus {
                border: 1px solid #00f5d4;
            }
        """)
        self._input_field.returnPressed.connect(self._handle_input_submit)
        input_layout.addWidget(self._input_field)

        self._send_btn = QPushButton("Send")
        self._send_btn.setFont(Theme.primary_font(9, bold=True))
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00d2ff, stop:1 #3a7bd5);
                color: #ffffff;
                border-radius: 6px;
                padding: 6px 12px;
                border: none;
            }
            QPushButton:hover {
                background: #00f5d4;
                color: #0d131f;
            }
        """)
        self._send_btn.clicked.connect(self._handle_input_submit)
        input_layout.addWidget(self._send_btn)

        self._expanded_layout.addLayout(input_layout)
        self._panel_layout.addWidget(self._expanded_widget)

        self._expanded_widget.setVisible(self._is_expanded)

        self._main_layout.addWidget(self._panel)

    def _style_header_btn(self, btn: QPushButton, is_close: bool = False) -> None:
        hover_color = "rgba(255, 77, 109, 180)" if is_close else "rgba(255, 255, 255, 45)"
        btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 18);
                color: #e2e8f0;
                border-radius: 12px;
                border: none;
                font-size: 9pt;
            }}
            QPushButton:hover {{
                background: {hover_color};
                color: #ffffff;
            }}
        """)

    def _update_chip_style(self, state: VisualState) -> None:
        palette = PALETTES.get(state, PALETTES[VisualState.IDLE])
        bg = palette.badge_bg
        text_col = palette.badge_text
        self._mic_chip.setText(palette.label)
        self._mic_chip.setStyleSheet(f"""
            QPushButton {{
                background: rgba({bg.red()}, {bg.green()}, {bg.blue()}, {bg.alpha()});
                color: rgb({text_col.red()}, {text_col.green()}, {text_col.blue()});
                border: 1px solid rgba({palette.primary.red()}, {palette.primary.green()}, {palette.primary.blue()}, 120);
                border-radius: 10px;
                padding: 3px 10px;
            }}
            QPushButton:hover {{
                background: rgba({bg.red()}, {bg.green()}, {bg.blue()}, {min(255, bg.alpha() + 50)});
            }}
        """)

    def _setup_animations(self) -> None:
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(220)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # -------------------------------------------------------------------------
    # State Synchronization
    # -------------------------------------------------------------------------

    def on_ui_update(self, update: UiUpdate) -> None:
        """Slot invoked from the runtime background thread; dispatches via Qt signal."""
        self.update_received.emit(update)

    def _apply_ui_update(self, update: UiUpdate) -> None:
        """Executes strictly on Qt main GUI thread."""
        self._current_update = update
        self._visual_state = update.visual_state

        # Update orb & waveform
        self._orb.set_visual_state(update.visual_state)
        self._orb.set_audio_level(update.audio_level)
        self._waveform.set_visual_state(update.visual_state)
        self._waveform.set_audio_level(update.audio_level)

        # Update status text
        self._status_label.setText(update.status_text)

        # Update mic chip
        self._update_chip_style(update.visual_state)

        # Update conversation bubbles
        if update.last_transcript:
            self._user_label.setText(f"You: \"{update.last_transcript}\"")
        if update.last_response:
            self._ai_label.setText(f"BUDDY: {update.last_response}")

        self.update()

    def update_settings(self, settings: DesktopSettings) -> None:
        self._settings = settings
        self._orb.set_intensity(settings.animation_intensity)
        self._waveform.set_intensity(settings.animation_intensity)
        self.reposition(settings.hud_position)
        self.update()

    # -------------------------------------------------------------------------
    # Window Actions & Interactivity
    # -------------------------------------------------------------------------

    def toggle_expanded_mode(self) -> None:
        self._is_expanded = not self._is_expanded
        self._expanded_widget.setVisible(self._is_expanded)
        self._expand_btn.setText("▼" if self._is_expanded else "▲")
        self.adjustSize()
        self.reposition(self._settings.hud_position)

    def _handle_input_submit(self) -> None:
        text = self._input_field.text().strip()
        if text:
            self._input_field.clear()
            self.submit_text_requested.emit(text)

    def reposition(self, position: HudPosition) -> None:
        """Place window safely within primary screen desktop geometry."""
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()

        margin = 24
        w = self.width() if self.width() > 100 else 360
        h = self.height() if self.height() > 100 else 180

        if position == HudPosition.BOTTOM_RIGHT:
            x = geo.right() - w - margin
            y = geo.bottom() - h - margin
        elif position == HudPosition.TOP_RIGHT:
            x = geo.right() - w - margin
            y = geo.top() + margin
        elif position == HudPosition.BOTTOM_LEFT:
            x = geo.left() + margin
            y = geo.bottom() - h - margin
        elif position == HudPosition.TOP_LEFT:
            x = geo.left() + margin
            y = geo.top() + margin
        elif position == HudPosition.TOP_CENTER:
            x = geo.left() + (geo.width() - w) // 2
            y = geo.top() + margin
        else:
            x = geo.right() - w - margin
            y = geo.bottom() - h - margin

        self.move(max(geo.left(), x), max(geo.top(), y))

    def show_hud(self) -> None:
        """Smoothly fade-in HUD without stealing focus."""
        target_opacity = self._settings.hud_opacity
        self.setWindowOpacity(0.0)
        self.show()
        if self._settings.animation_intensity != AnimationIntensity.OFF:
            self._fade_anim.stop()
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(target_opacity)
            self._fade_anim.start()
        else:
            self.setWindowOpacity(target_opacity)

    def hide_hud(self) -> None:
        """Smoothly fade-out and hide to tray."""
        if self._settings.animation_intensity != AnimationIntensity.OFF:
            self._fade_anim.stop()
            self._fade_anim.setStartValue(self.windowOpacity())
            self._fade_anim.setEndValue(0.0)
            self._fade_anim.finished.connect(self._on_hide_finished)
            self._fade_anim.start()
        else:
            self.hide()

    def _on_hide_finished(self) -> None:
        try:
            self._fade_anim.finished.disconnect(self._on_hide_finished)
        except Exception:
            pass
        self.hide()

    # -------------------------------------------------------------------------
    # Drag-to-Move
    # -------------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None

    # -------------------------------------------------------------------------
    # Custom Glassmorphism Painting
    # -------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRectF(self._panel.geometry())
        radius = float(Theme.CORNER_RADIUS)

        palette = PALETTES.get(self._visual_state, PALETTES[VisualState.IDLE])

        # 1. Dark glass background
        if self._settings.force_opaque:
            bg_brush = QBrush(QColor(14, 18, 27, 255))
        else:
            bg_grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
            c1 = QColor(14, 18, 28, 220)
            c2 = QColor(20, 26, 40, 235)
            bg_grad.setColorAt(0.0, c1)
            bg_grad.setColorAt(1.0, c2)
            bg_brush = QBrush(bg_grad)

        painter.setBrush(bg_brush)

        # 2. Glowing glass accent border
        border_col = QColor(palette.primary)
        border_col.setAlpha(95)
        painter.setPen(QPen(border_col, Theme.BORDER_WIDTH))
        painter.drawRoundedRect(rect, radius, radius)

        # 3. Soft top-edge light catch
        top_line = QRectF(rect.x() + radius, rect.y() + 1.0, rect.width() - (radius * 2), 1.0)
        painter.setPen(QPen(QColor(255, 255, 255, 60), 1.0))
        painter.drawLine(top_line.topLeft(), top_line.topRight())
