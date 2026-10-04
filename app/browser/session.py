"""BUDDY Browser Session Lifecycle Management.

Tracks session status, activity timestamps, timeout expiration,
and isolates browser contexts with clean automation profiles.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from app.browser.browser import BrowserManager
from app.browser.config import BrowserConfig
from app.browser.exceptions import BrowserSessionError, BrowserTimeoutError
from app.browser.models import BrowserPageInfo, BrowserSessionStatus
from app.browser.tabs import BrowserTab, TabManager

logger = logging.getLogger("buddy.browser.session")


class BrowserSession:
    """Represents an isolated, policy-controlled browser session."""

    def __init__(
        self,
        session_id: Optional[str] = None,
        config: Optional[BrowserConfig] = None,
        browser_manager: Optional[BrowserManager] = None,
    ) -> None:
        self.session_id = session_id or f"session_{uuid.uuid4().hex[:8]}"
        self._config = config or BrowserConfig()
        self._browser_manager = browser_manager or BrowserManager(self._config)
        self._context: Any = None
        self._tab_manager = TabManager(max_tabs=self._config.browser_max_tabs)

        self.status = BrowserSessionStatus.CREATED
        self.created_at = time.time()
        self.last_activity = time.time()
        self.timeout_seconds = self._config.browser_session_timeout_seconds

    @property
    def config(self) -> BrowserConfig:
        return self._config

    @property
    def tab_manager(self) -> TabManager:
        return self._tab_manager

    @property
    def is_expired(self) -> bool:
        """Check if session has exceeded its configured inactivity timeout."""
        if self.status in (BrowserSessionStatus.CLOSED, BrowserSessionStatus.ERROR):
            return True
        return (time.time() - self.last_activity) > self.timeout_seconds

    def touch(self) -> None:
        """Update last activity timestamp and verify session has not timed out."""
        if self.is_expired and self.status == BrowserSessionStatus.RUNNING:
            self.status = BrowserSessionStatus.CLOSED
            raise BrowserTimeoutError(
                f"Browser session '{self.session_id}' timed out after {self.timeout_seconds:.1f} seconds of inactivity."
            )
        self.last_activity = time.time()

    async def start(self) -> None:
        """Initialize isolated context and initial active blank tab."""
        if self.status == BrowserSessionStatus.RUNNING:
            return

        self.status = BrowserSessionStatus.STARTING
        try:
            self._context = await self._browser_manager.create_isolated_context()

            # Create initial tab
            page = None
            if self._context and hasattr(self._context, "new_page"):
                page = await self._context.new_page()

            initial_tab = BrowserTab(page=page, url="about:blank", title="New Tab")
            self._tab_manager.add_tab(initial_tab, set_active=True)

            self.status = BrowserSessionStatus.RUNNING
            self.touch()
            logger.info("Browser session '%s' started with initial tab '%s'", self.session_id, initial_tab.tab_id)
        except Exception as e:
            self.status = BrowserSessionStatus.ERROR
            logger.error("Failed to start browser session '%s': %s", self.session_id, e)
            raise BrowserSessionError(f"Failed to start session: {e}") from e

    async def new_tab(self, url: str = "about:blank") -> BrowserTab:
        """Create a new tab within this isolated session."""
        self.touch()
        if self.status != BrowserSessionStatus.RUNNING:
            await self.start()

        page = None
        if self._context and hasattr(self._context, "new_page"):
            page = await self._context.new_page()

        tab = BrowserTab(page=page, url=url, title="New Tab")
        self._tab_manager.add_tab(tab, set_active=True)
        return tab

    async def close_tab(self, tab_id: Optional[str] = None) -> None:
        """Close specified tab or active tab."""
        self.touch()
        target_tab = self._tab_manager.get_tab(tab_id) if tab_id else self._tab_manager.get_active_tab()

        if target_tab.page and hasattr(target_tab.page, "close"):
            try:
                await target_tab.page.close()
            except Exception as e:
                logger.warning("Error closing page for tab '%s': %s", target_tab.tab_id, e)

        self._tab_manager.remove_tab(target_tab.tab_id)

    async def switch_tab(self, tab_id: str) -> BrowserTab:
        """Switch active tab focus."""
        self.touch()
        return self._tab_manager.set_active_tab(tab_id)

    def get_active_tab(self) -> BrowserTab:
        self.touch()
        return self._tab_manager.get_active_tab()

    async def close(self) -> None:
        """Close all tabs, context, and release session resources."""
        self.status = BrowserSessionStatus.CLOSING
        for tab in self._tab_manager.list_tabs():
            if tab.page and hasattr(tab.page, "close"):
                try:
                    await tab.page.close()
                except Exception:
                    pass
            tab.mark_closed()

        if self._context and hasattr(self._context, "close"):
            try:
                await self._context.close()
            except Exception as e:
                logger.warning("Error closing browser context for session '%s': %s", self.session_id, e)
            self._context = None

        self.status = BrowserSessionStatus.CLOSED
        logger.info("Browser session '%s' closed cleanly.", self.session_id)
