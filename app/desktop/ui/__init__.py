"""BUDDY Desktop UI Components Package."""

from app.desktop.ui.hud import GlassHudWindow
from app.desktop.ui.orb import AnimatedOrbWidget
from app.desktop.ui.settings_dialog import SettingsDialog
from app.desktop.ui.theme import PALETTES, StatePalette, Theme
from app.desktop.ui.tray import BuddySystemTray
from app.desktop.ui.waveform import WaveformWidget

__all__ = [
    "GlassHudWindow",
    "AnimatedOrbWidget",
    "WaveformWidget",
    "SettingsDialog",
    "BuddySystemTray",
    "Theme",
    "PALETTES",
    "StatePalette",
]
