"""BUDDY Desktop Package.

Provides persistent background runtime, animated glass HUD, system tray integration,
and audio-reactive visualization.
"""

from app.desktop.dispatch import dispatch_voice_intent, recover_state_to_idle
from app.desktop.settings import AnimationIntensity, DesktopSettings, HudPosition, SettingsStore
from app.desktop.single_instance import SingleInstanceGuard
from app.desktop.startup import LoginStartupManager

__all__ = [
    "dispatch_voice_intent",
    "recover_state_to_idle",
    "DesktopSettings",
    "SettingsStore",
    "AnimationIntensity",
    "HudPosition",
    "SingleInstanceGuard",
    "LoginStartupManager",
]
