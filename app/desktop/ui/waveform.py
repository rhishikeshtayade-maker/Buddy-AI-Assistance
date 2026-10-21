"""BUDDY Audio-Reactive Waveform Visualizer.

Renders responsive frequency bars reflecting microphone input and speech synthesis levels.
Uses low-overhead procedural bars with decayed smoothing.
"""

from __future__ import annotations

import math
import random
from typing import Optional

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from app.desktop.bridge import VisualState
from app.desktop.settings import AnimationIntensity
from app.desktop.ui.theme import PALETTES


class WaveformWidget(QWidget):
    """Audio-reactive waveform visualizer bar component."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        num_bars: int = 18,
        intensity: AnimationIntensity = AnimationIntensity.FULL,
    ) -> None:
        super().__init__(parent)
        self._num_bars = num_bars
        self._intensity = intensity
        self._visual_state = VisualState.IDLE
        self._audio_level = 0.0

        # Bar heights [0.0, 1.0]
        self._bars: list[float] = [0.05] * num_bars
        self._target_bars: list[float] = [0.05] * num_bars

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._configure_timer()

        self.setMinimumSize(QSize(120, 24))
        self.setMaximumHeight(36)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def _configure_timer(self) -> None:
        if self._intensity == AnimationIntensity.FULL:
            self._timer.start(33)
        elif self._intensity == AnimationIntensity.REDUCED:
            self._timer.start(83)
        else:
            self._timer.stop()

    def set_intensity(self, intensity: AnimationIntensity) -> None:
        self._intensity = intensity
        self._configure_timer()
        self.update()

    def set_visual_state(self, state: VisualState) -> None:
        self._visual_state = state
        self.update()

    def set_audio_level(self, level: float) -> None:
        self._audio_level = max(0.0, min(1.0, level))
        self._recompute_targets()
        if self._intensity == AnimationIntensity.OFF:
            self._bars = list(self._target_bars)
            self.update()

    def _recompute_targets(self) -> None:
        is_active = self._visual_state in (VisualState.LISTENING, VisualState.SPEAKING)
        base_h = 0.08
        level = self._audio_level if is_active else 0.0

        for i in range(self._num_bars):
            # Center bell curve weighting
            norm_idx = abs(i - (self._num_bars / 2.0)) / (self._num_bars / 2.0)
            center_weight = max(0.2, 1.0 - (norm_idx * 0.7))

            if level > 0.01:
                jitter = (random.random() * 0.4) + 0.8
                h = min(1.0, base_h + (level * center_weight * jitter))
            elif is_active:
                # Small standby ripple
                h = base_h + (0.05 * math.sin(i * 0.6))
            else:
                h = base_h
            self._target_bars[i] = h

    def _on_tick(self) -> None:
        # Smooth interpolation toward targets
        alpha = 0.35 if self._intensity == AnimationIntensity.FULL else 0.55
        changed = False
        for i in range(self._num_bars):
            diff = self._target_bars[i] - self._bars[i]
            if abs(diff) > 0.005:
                self._bars[i] += diff * alpha
                changed = True
            else:
                self._bars[i] = self._target_bars[i]

        if changed or self._visual_state in (VisualState.LISTENING, VisualState.SPEAKING):
            self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        palette = PALETTES.get(self._visual_state, PALETTES[VisualState.IDLE])
        rect = self.rect()
        w = rect.width()
        h = rect.height()
        mid_y = h / 2.0

        bar_spacing = 3.0
        total_spacing = bar_spacing * (self._num_bars - 1)
        bar_w = max(2.5, (w - total_spacing) / self._num_bars)

        start_x = (w - (bar_w * self._num_bars + total_spacing)) / 2.0

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, palette.primary)
        grad.setColorAt(0.5, palette.secondary)
        grad.setColorAt(1.0, palette.primary)

        brush = QBrush(grad)
        pen = Qt.PenStyle.NoPen
        painter.setPen(pen)
        painter.setBrush(brush)

        for i, norm_h in enumerate(self._bars):
            x = start_x + (i * (bar_w + bar_spacing))
            bar_height = max(3.0, norm_h * (h - 4.0))
            y = mid_y - (bar_height / 2.0)
            corner_r = min(bar_w / 2.0, 2.0)
            painter.drawRoundedRect(QRectF(x, y, bar_w, bar_height), corner_r, corner_r)
