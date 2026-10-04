"""BUDDY Browser Controlled Screenshot Capture.

Captures in-memory screenshots for visual understanding without persisting
raw image buffers to disk or cloud AI unless explicitly authorized.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional
from pydantic import BaseModel, Field

from app.browser.config import BrowserConfig
from app.browser.exceptions import BrowserSecurityError

logger = logging.getLogger("buddy.browser.screenshots")


class BrowserScreenshot(BaseModel):
    """In-memory screenshot representation."""
    format: str = "png"
    base64_data: str = Field(..., description="Base64-encoded image data")
    width: int = 1280
    height: int = 720
    is_sensitive_page: bool = False

    model_config = {"extra": "forbid"}

    def get_bytes(self) -> bytes:
        return base64.b64decode(self.base64_data)


class ScreenshotManager:
    """Manages in-memory browser screenshots with privacy protections."""

    def __init__(self, config: Optional[BrowserConfig] = None) -> None:
        self._config = config or BrowserConfig()

    def validate_screenshot_permitted(self, is_sensitive_page: bool = False) -> None:
        """Verify screenshot capture is enabled and safe."""
        if not self._config.browser_screenshot_enabled:
            raise BrowserSecurityError("Browser screenshots are disabled in configuration.")

        if is_sensitive_page:
            logger.warning("Capturing screenshot on page flagged as containing sensitive/credential fields.")

    def wrap_screenshot_bytes(
        self,
        image_bytes: bytes,
        width: int = 1280,
        height: int = 720,
        is_sensitive_page: bool = False,
    ) -> BrowserScreenshot:
        """Encode raw image bytes into an in-memory BrowserScreenshot model."""
        b64 = base64.b64encode(image_bytes).decode("ascii")
        return BrowserScreenshot(
            format="png",
            base64_data=b64,
            width=width,
            height=height,
            is_sensitive_page=is_sensitive_page,
        )
