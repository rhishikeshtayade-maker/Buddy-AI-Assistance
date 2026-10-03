"""BUDDY Screen Capture & State Fingerprinting Subsystem.

Provides lightweight screen dimension queries and deterministic visual state fingerprinting.
Used by the interaction layer to prevent clicking on stale or modified screens.
"""

from __future__ import annotations

import ctypes
import hashlib
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional, Tuple

logger = logging.getLogger("buddy.vision.screen")


class ScreenManager(ABC):
    """Abstract interface for screen inspection and state fingerprinting."""

    @abstractmethod
    def get_screen_dimensions(self) -> Tuple[int, int]:
        """Return (width, height) of the primary display."""
        ...

    @abstractmethod
    def get_screen_fingerprint(self) -> str:
        """Compute a compact cryptographic hash of the current screen state."""
        ...


class WindowsScreenManager(ScreenManager):
    """Screen manager using standard Windows user32 APIs without third-party heavy dependencies."""

    def __init__(self) -> None:
        self._last_fingerprint: str = ""
        self._last_ts: float = 0.0

    def get_screen_dimensions(self) -> Tuple[int, int]:
        try:
            user32 = ctypes.windll.user32
            width = user32.GetSystemMetrics(0)   # SM_CXSCREEN
            height = user32.GetSystemMetrics(1)  # SM_CYSCREEN
            if width > 0 and height > 0:
                return (width, height)
        except Exception as e:
            logger.warning("Could not query Windows screen dimensions: %s", e)
        return (1920, 1080)

    def get_screen_fingerprint(self) -> str:
        """Generate a screen fingerprint based on dimensions, foreground window, and sample metrics."""
        try:
            user32 = ctypes.windll.user32
            w, h = self.get_screen_dimensions()
            fg_hwnd = user32.GetForegroundWindow()

            # Read window title of foreground window
            length = user32.GetWindowTextLengthW(fg_hwnd)
            title = ""
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(fg_hwnd, buf, length + 1)
                title = buf.value

            # Combine resolution, active window handle, and title into SHA-256 fingerprint
            raw = f"win:{w}x{h}:hwnd:{fg_hwnd}:title:{title}"
            return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        except Exception as e:
            logger.warning("Error generating Windows screen fingerprint: %s", e)
            return "win_default_fp"


class MockScreenManager(ScreenManager):
    """Deterministic screen manager for automated testing and CI environments."""

    def __init__(
        self,
        dimensions: Tuple[int, int] = (1920, 1080),
        initial_fingerprint: str = "screen_fp_alpha_001",
    ) -> None:
        self.dimensions = dimensions
        self.current_fingerprint = initial_fingerprint
        self.call_count = 0

    def get_screen_dimensions(self) -> Tuple[int, int]:
        return self.dimensions

    def get_screen_fingerprint(self) -> str:
        self.call_count += 1
        return self.current_fingerprint

    def simulate_screen_change(self, new_fingerprint: str = "screen_fp_beta_002") -> None:
        """Trigger an artificial screen state change for testing stale target detection."""
        self.current_fingerprint = new_fingerprint
