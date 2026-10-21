"""BUDDY Desktop Settings.

User-adjustable desktop preferences (HUD appearance, microphone behaviour,
startup-at-login opt-in), persisted as a small JSON document under the data
directory. These settings never contain secrets, transcripts, or audio.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger("buddy.desktop.settings")

DEFAULT_SETTINGS_PATH = Path("data") / "desktop_settings.json"


class AnimationIntensity(str, Enum):
    """HUD animation level. OFF repaints only on state change (reduced-motion)."""

    FULL = "full"
    REDUCED = "reduced"
    OFF = "off"


class HudPosition(str, Enum):
    """Screen anchor for the floating HUD."""

    TOP_RIGHT = "top_right"
    BOTTOM_RIGHT = "bottom_right"
    TOP_LEFT = "top_left"
    BOTTOM_LEFT = "bottom_left"
    TOP_CENTER = "top_center"


class DesktopSettings(BaseModel):
    """Strongly typed desktop preferences with safe defaults."""

    model_config = {"extra": "ignore", "validate_assignment": True}

    animation_intensity: AnimationIntensity = AnimationIntensity.FULL
    hud_opacity: float = Field(default=0.92, ge=0.4, le=1.0)
    hud_position: HudPosition = HudPosition.BOTTOM_RIGHT
    sound_enabled: bool = True
    # Opt-in only. Never enabled implicitly.
    start_at_login: bool = False
    start_minimized_to_tray: bool = False
    listen_on_startup: bool = True
    # 0 disables auto-resume: once paused, listening resumes only on explicit request.
    pause_auto_resume_minutes: int = Field(default=0, ge=0, le=240)
    expanded_mode: bool = False
    # Force an opaque panel when translucency/GPU compositing is unavailable or undesired.
    force_opaque: bool = False


class SettingsStore:
    """Load/save ``DesktopSettings`` atomically; corrupt files fall back to defaults."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self._path = Path(path) if path else DEFAULT_SETTINGS_PATH

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> DesktopSettings:
        if not self._path.exists():
            return DesktopSettings()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("settings document must be a JSON object")
            return DesktopSettings.model_validate(raw)
        except (OSError, ValueError, ValidationError) as err:
            logger.warning("Desktop settings unreadable (%s); using defaults.", type(err).__name__)
            return DesktopSettings()

    def save(self, settings: DesktopSettings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(settings.model_dump(mode="json"), indent=2, sort_keys=True)
        fd, tmp = tempfile.mkstemp(prefix=".desktop_settings_", dir=str(self._path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
