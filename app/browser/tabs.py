"""BUDDY Browser Tab Management.

Tracks open browser tabs, active tab focus, and enforces maximum tab quotas.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

from app.browser.exceptions import BrowserTabError
from app.browser.models import BrowserTabStatus

logger = logging.getLogger("buddy.browser.tabs")


class BrowserTab:
    """Represents an isolated browser tab page."""

    def __init__(
        self,
        tab_id: Optional[str] = None,
        page: Any = None,
        url: str = "about:blank",
        title: str = "",
    ) -> None:
        self.tab_id = tab_id or f"tab_{uuid.uuid4().hex[:8]}"
        self.page = page  # Playwright Page handle or mock
        self.url = url
        self.title = title
        self.status = BrowserTabStatus.ACTIVE
        self.fingerprint = ""

    def mark_closed(self) -> None:
        self.status = BrowserTabStatus.CLOSED
        self.page = None


class TabManager:
    """Manages tabs within a browser session, enforcing maximum tab constraints."""

    def __init__(self, max_tabs: int = 5) -> None:
        self._max_tabs = max_tabs
        self._tabs: Dict[str, BrowserTab] = {}
        self._active_tab_id: Optional[str] = None

    @property
    def max_tabs(self) -> int:
        return self._max_tabs

    @property
    def active_tab_id(self) -> Optional[str]:
        return self._active_tab_id

    def list_tabs(self) -> List[BrowserTab]:
        return [t for t in self._tabs.values() if t.status != BrowserTabStatus.CLOSED]

    def get_tab(self, tab_id: str) -> BrowserTab:
        tab = self._tabs.get(tab_id)
        if not tab or tab.status == BrowserTabStatus.CLOSED:
            raise BrowserTabError(f"Tab '{tab_id}' does not exist or has been closed.")
        return tab

    def get_active_tab(self) -> BrowserTab:
        if not self._active_tab_id or self._active_tab_id not in self._tabs:
            # Fallback to first open tab
            open_tabs = self.list_tabs()
            if not open_tabs:
                raise BrowserTabError("No active tabs available in session.")
            self._active_tab_id = open_tabs[0].tab_id

        tab = self._tabs[self._active_tab_id]
        if tab.status == BrowserTabStatus.CLOSED:
            raise BrowserTabError("Active tab is closed.")
        return tab

    def add_tab(self, tab: BrowserTab, set_active: bool = True) -> BrowserTab:
        open_tabs = self.list_tabs()
        if len(open_tabs) >= self._max_tabs:
            raise BrowserTabError(
                f"Maximum open tabs limit ({self._max_tabs}) exceeded. Close a tab before opening a new one."
            )

        self._tabs[tab.tab_id] = tab
        if set_active or not self._active_tab_id:
            self.set_active_tab(tab.tab_id)
        else:
            tab.status = BrowserTabStatus.BACKGROUND

        logger.info("Added tab '%s' (active=%s, total=%d)", tab.tab_id, self._active_tab_id == tab.tab_id, len(self.list_tabs()))
        return tab

    def set_active_tab(self, tab_id: str) -> BrowserTab:
        tab = self.get_tab(tab_id)
        for t in self._tabs.values():
            if t.status == BrowserTabStatus.ACTIVE and t.tab_id != tab_id:
                t.status = BrowserTabStatus.BACKGROUND

        tab.status = BrowserTabStatus.ACTIVE
        self._active_tab_id = tab_id
        logger.info("Switched active tab to '%s'", tab_id)
        return tab

    def remove_tab(self, tab_id: str) -> None:
        if tab_id in self._tabs:
            tab = self._tabs[tab_id]
            tab.mark_closed()
            logger.info("Closed tab '%s'", tab_id)
            if self._active_tab_id == tab_id:
                open_tabs = self.list_tabs()
                self._active_tab_id = open_tabs[0].tab_id if open_tabs else None
