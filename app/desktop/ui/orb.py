"""BUDDY Central Animated AI Orb Widget.

Renders an organic, multi-layered glass sphere with dynamic radial glow,
rotating coronas, breathing pulses, and audio-reactive energy expansion.
"""

from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from app.desktop.bridge import VisualState
from app.desktop.settings import AnimationIntensity
from app.desktop.ui.theme import PALETTES, Theme


class AnimatedOrbWidget(QWidget):
    """Central AI Orb visualizer with state-synchronized animations."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        intensity: AnimationIntensity = AnimationIntensity.FULL,
    ) -> None:
        super().__init__(parent)
        self._intensity = intensity
        self._visual_state = VisualState.IDLE
        self._audio_level = 0.0

        # Animation parameters
        self._time = 0.0
        self._rotation_angle = 0.0
        self._pulse_phase = 0.0

        # Animation timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._configure_timer()

        self.setMinimumSize(QSize(90, 90))
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def _configure_timer(self) -> None:
        if self._intensity == AnimationIntensity.FULL:
            # ~33 ms (30 FPS)
            self._timer.start(33)
        elif self._intensity == AnimationIntensity.REDUCED:
            # ~83 ms (12 FPS)
            self._timer.start(83)
        else:
            self._timer.stop()

    def set_intensity(self, intensity: AnimationIntensity) -> None:
        self._intensity = intensity
        self._configure_timer()
        self.update()

    def set_visual_state(self, state: VisualState) -> None:
        if self._visual_state != state:
            self._visual_state = state
            self.update()

    def set_audio_level(self, level: float) -> None:
        self._audio_level = max(0.0, min(1.0, level))
        if self._intensity == AnimationIntensity.OFF:
            self.update()

    def _on_tick(self) -> None:
        # Increment time based on state speed
        if self._visual_state == VisualState.THINKING:
            speed = 0.08
            self._rotation_angle = (self._rotation_angle + 6.0) % 360.0
        elif self._visual_state in (VisualState.LISTENING, VisualState.SPEAKING):
            speed = 0.06
            self._rotation_angle = (self._rotation_angle + 2.5) % 360.0
        elif self._visual_state == VisualState.EXECUTING:
            speed = 0.05
            self._rotation_angle = (self._rotation_angle + 4.0) % 360.0
        elif self._visual_state == VisualState.PAUSED:
            speed = 0.015
        else:
            # Idle slow breathing
            speed = 0.03
            self._rotation_angle = (self._rotation_angle + 0.8) % 360.0

        self._time += speed
        self._pulse_phase = math.sin(self._time)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        palette = PALETTES.get(self._visual_state, PALETTES[VisualState.IDLE])
        rect = self.rect()
        center = QPointF(rect.width() / 2.0, rect.height() / 2.0)
        base_radius = min(rect.width(), rect.height()) / 2.0 - 8.0

        if base_radius <= 5.0:
            return

        # Breathing scale: varies with pulse_phase + audio_level
        pulse_expansion = (self._pulse_phase * 0.06) + (self._audio_level * 0.18)
        radius = base_radius * (1.0 + pulse_expansion)

        # 1. Outer Glow halo
        glow_radius = radius * 1.35
        glow_grad = QRadialGradient(center, glow_radius)
        glow_color = QColor(palette.glow)
        glow_color.setAlpha(int(glow_color.alpha() * (0.8 + 0.2 * self._pulse_phase)))
        glow_grad.setColorAt(0.0, glow_color)
        glow_grad.setColorAt(0.6, QColor(glow_color.red(), glow_color.green(), glow_color.blue(), int(glow_color.alpha() * 0.3)))
        glow_grad.setColorAt(1.0, QColor(glow_color.red(), glow_color.green(), glow_color.blue(), 0))
        painter.setBrush(QBrush(glow_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, glow_radius, glow_radius)

        # 2. Rotating corona / arcs (especially visible in THINKING, LISTENING, EXECUTING)
        if self._visual_state in (VisualState.THINKING, VisualState.EXECUTING, VisualState.LISTENING):
            arc_radius = radius + 3.0
            arc_rect = QRectF(center.x() - arc_radius, center.y() - arc_radius, arc_radius * 2, arc_radius * 2)
            conical = QConicalGradient(center, self._rotation_angle)
            conical.setColorAt(0.0, palette.primary)
            conical.setColorAt(0.5, QColor(0, 0, 0, 0))
            conical.setColorAt(0.8, palette.secondary)
            conical.setColorAt(1.0, palette.primary)

            arc_pen = QPen(QBrush(conical), 2.2)
            arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(arc_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(arc_rect, int(self._rotation_angle * 16), 140 * 16)
            painter.drawArc(arc_rect, int((self._rotation_angle + 180) * 16), 100 * 16)

        # 3. Orb core radial gradient (depth and glass highlight)
        core_grad = QRadialGradient(center.x() - radius * 0.25, center.y() - radius * 0.25, radius)
        # Highlight spot
        highlight_color = QColor(255, 255, 255, 220)
        primary_color = palette.primary
        secondary_color = palette.secondary

        core_grad.setColorAt(0.0, highlight_color)
        core_grad.setColorAt(0.2, primary_color)
        core_grad.setColorAt(0.7, secondary_color)
        core_grad.setColorAt(1.0, QColor(10, 15, 25, 240))

        painter.setBrush(QBrush(core_grad))
        border_pen = QPen(QColor(255, 255, 255, 70), 1.2)
        painter.setPen(border_pen)
        painter.drawEllipse(center, radius, radius)

        # 4. Inner glass reflection crescent
        crescent_rect = QRectF(center.x() - radius * 0.65, center.y() - radius * 0.75, radius * 1.3, radius * 0.8)
        refl_grad = QLinearGradient(crescent_rect.topLeft(), crescent_rect.bottomLeft())
        refl_grad.setColorAt(0.0, QColor(255, 255, 255, 110))
        refl_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(refl_grad))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(crescent_rect)
