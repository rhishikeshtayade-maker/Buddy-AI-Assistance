"""BUDDY Browser Engine and Playwright Controller.

Controls browser process launching, headless execution, isolated browser contexts,
and clean automation profiles.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.browser.config import BrowserConfig
from app.browser.exceptions import BrowserError, BrowserSessionError
from app.browser.models import BrowserEngine

logger = logging.getLogger("buddy.browser.browser")

# Check if playwright is importable
try:
    from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    Playwright = Any  # type: ignore
    Browser = Any  # type: ignore
    BrowserContext = Any  # type: ignore


class BrowserManager:
    """Manages the underlying Playwright browser process and context isolation."""

    def __init__(self, config: Optional[BrowserConfig] = None) -> None:
        self._config = config or BrowserConfig()
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._engine = self._config.browser_engine

    @property
    def is_running(self) -> bool:
        return self._browser is not None

    @property
    def config(self) -> BrowserConfig:
        return self._config

    async def start(self) -> None:
        """Launch the browser engine in an isolated, clean state."""
        if not self._config.browser_enabled:
            raise BrowserError("Browser automation subsystem is disabled in configuration.")

        if self._browser is not None:
            return

        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright is not installed. Browser will run in simulated test mode.")
            return

        try:
            self._playwright = await async_playwright().start()
            headless = self._config.browser_headless

            # Launch Chromium or Edge channel
            if self._engine == BrowserEngine.EDGE:
                try:
                    self._browser = await self._playwright.chromium.launch(
                        channel="msedge",
                        headless=headless,
                    )
                except Exception as edge_err:
                    logger.warning("Failed to launch Edge channel (%s); falling back to default Chromium", edge_err)
                    self._browser = await self._playwright.chromium.launch(headless=headless)
            else:
                try:
                    self._browser = await self._playwright.chromium.launch(headless=headless)
                except Exception as ch_err:
                    # If standard chromium driver is not installed, try system chrome or edge channel
                    logger.warning("Default Chromium launch failed (%s); trying system chrome channel", ch_err)
                    try:
                        self._browser = await self._playwright.chromium.launch(channel="chrome", headless=headless)
                    except Exception:
                        self._browser = await self._playwright.chromium.launch(channel="msedge", headless=headless)

            logger.info("Launched browser engine %s (headless=%s)", self._engine.value, headless)
        except Exception as e:
            logger.error("Failed to start browser engine: %s", e)
            await self.stop()
            raise BrowserSessionError(f"Could not launch browser: {e}") from e

    async def create_isolated_context(self) -> Any:
        """Create a clean, isolated browser context with no stored user cookies or profile data."""
        if self._browser is None:
            if not PLAYWRIGHT_AVAILABLE:
                # Return mock context for unit testing
                return None
            await self.start()

        if self._browser is None:
            return None

        context = await self._browser.new_context(
            accept_downloads=True,
            ignore_https_errors=False,
            viewport={"width": 1280, "height": 720},
        )
        return context

    async def stop(self) -> None:
        """Safely terminate browser process and Playwright controller."""
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception as e:
                logger.warning("Error closing browser: %s", e)
            self._browser = None

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as e:
                logger.warning("Error stopping Playwright: %s", e)
            self._playwright = None

        logger.info("Browser process stopped cleanly.")
