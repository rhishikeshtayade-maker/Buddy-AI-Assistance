"""BUDDY Desktop UI Theme & Design Tokens.

Curated glassmorphism design system featuring soft cyan, blue, and purple
accent lighting, dark translucent panels, and state-reactive color palettes.
"""

from __future__ import annotations

from dataclasses import dataclass
from PySide6.QtGui import QColor, QFont, QLinearGradient

from app.desktop.bridge import VisualState


@dataclass(frozen=True)
class StatePalette:
    """Colors associated with a specific visual state."""

    primary: QColor
    secondary: QColor
    glow: QColor
    badge_bg: QColor
    badge_text: QColor
    label: str


# State color definitions
PALETTES: dict[VisualState, StatePalette] = {
    VisualState.STARTING: StatePalette(
        primary=QColor(0, 180, 216),
        secondary=QColor(114, 9, 183),
        glow=QColor(0, 180, 216, 120),
        badge_bg=QColor(0, 180, 216, 40),
        badge_text=QColor(144, 224, 239),
        label="STARTING",
    ),
    VisualState.IDLE: StatePalette(
        primary=QColor(0, 210, 255),
        secondary=QColor(58, 123, 213),
        glow=QColor(0, 210, 255, 90),
        badge_bg=QColor(0, 210, 255, 30),
        badge_text=QColor(128, 237, 255),
        label="READY",
    ),
    VisualState.LISTENING: StatePalette(
        primary=QColor(0, 245, 212),
        secondary=QColor(155, 93, 229),
        glow=QColor(0, 245, 212, 180),
        badge_bg=QColor(0, 245, 212, 50),
        badge_text=QColor(204, 255, 245),
        label="LISTENING",
    ),
    VisualState.THINKING: StatePalette(
        primary=QColor(157, 80, 187),
        secondary=QColor(110, 72, 170),
        glow=QColor(157, 80, 187, 160),
        badge_bg=QColor(157, 80, 187, 45),
        badge_text=QColor(230, 200, 255),
        label="THINKING",
    ),
    VisualState.EXECUTING: StatePalette(
        primary=QColor(255, 183, 3),
        secondary=QColor(0, 180, 216),
        glow=QColor(255, 183, 3, 150),
        badge_bg=QColor(255, 183, 3, 40),
        badge_text=QColor(255, 229, 153),
        label="EXECUTING",
    ),
    VisualState.SPEAKING: StatePalette(
        primary=QColor(0, 180, 216),
        secondary=QColor(144, 224, 239),
        glow=QColor(0, 180, 216, 170),
        badge_bg=QColor(0, 180, 216, 45),
        badge_text=QColor(202, 240, 248),
        label="SPEAKING",
    ),
    VisualState.ERROR: StatePalette(
        primary=QColor(255, 77, 109),
        secondary=QColor(201, 24, 74),
        glow=QColor(255, 77, 109, 180),
        badge_bg=QColor(255, 77, 109, 45),
        badge_text=QColor(255, 180, 195),
        label="ERROR",
    ),
    VisualState.SHUTTING_DOWN: StatePalette(
        primary=QColor(108, 117, 125),
        secondary=QColor(73, 80, 87),
        glow=QColor(108, 117, 125, 80),
        badge_bg=QColor(108, 117, 125, 40),
        badge_text=QColor(206, 212, 218),
        label="STOPPING",
    ),
    VisualState.PAUSED: StatePalette(
        primary=QColor(255, 183, 3),
        secondary=QColor(108, 117, 125),
        glow=QColor(255, 183, 3, 70),
        badge_bg=QColor(255, 183, 3, 30),
        badge_text=QColor(255, 220, 120),
        label="PAUSED",
    ),
}


class Theme:
    """Design constants for Glass HUD."""

    # Panel geometry
    CORNER_RADIUS = 20
    BORDER_WIDTH = 1.2
    PADDING = 16

    # Glass background colors (dark mode)
    BG_BASE = QColor(14, 18, 27, 215)
    BG_CARD = QColor(22, 28, 42, 180)
    BG_CARD_HOVER = QColor(32, 40, 60, 210)
    BG_INPUT = QColor(10, 14, 22, 220)

    # Fully opaque background colors (for dialogs & fallback mode)
    BG_OPAQUE_BASE = QColor(14, 18, 27, 255)       # #0e121b
    BG_OPAQUE_SURFACE = QColor(22, 28, 42, 255)    # #161c2a
    BG_OPAQUE_ELEVATED = QColor(30, 38, 56, 255)   # #1e2638

    # Glass border
    BORDER_SUBTLE = QColor(255, 255, 255, 28)
    BORDER_ACTIVE = QColor(0, 210, 255, 90)

    # Text hierarchy
    TEXT_PRIMARY = QColor(245, 248, 255)
    TEXT_SECONDARY = QColor(165, 178, 205)
    TEXT_MUTED = QColor(115, 128, 155)

    # Accent colors
    CYAN_ACCENT = QColor(0, 210, 255)
    PURPLE_ACCENT = QColor(157, 80, 187)
    BLUE_ACCENT = QColor(58, 123, 213)

    @staticmethod
    def primary_font(size: int = 10, bold: bool = False) -> QFont:
        font = QFont("Segoe UI", size)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        if bold:
            font.setBold(True)
        return font

    @staticmethod
    def mono_font(size: int = 9) -> QFont:
        font = QFont("Consolas", size)
        font.setStyleHint(QFont.StyleHint.Monospace)
        return font
