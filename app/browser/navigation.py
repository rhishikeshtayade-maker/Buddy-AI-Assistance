"""BUDDY Browser Controlled Navigation.

Coordinates URL validation, redirect monitoring, bounded timeouts,
and post-navigation state synchronization.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.browser.config import BrowserConfig
from app.browser.exceptions import BrowserNavigationError, BrowserSecurityError
from app.browser.policy import BrowserPolicy
from app.browser.tabs import BrowserTab

logger = logging.getLogger("buddy.browser.navigation")


class NavigationManager:
    """Manages secure navigation within active browser tabs."""

    def __init__(
        self,
        policy: Optional[BrowserPolicy] = None,
        config: Optional[BrowserConfig] = None,
    ) -> None:
        self._policy = policy or BrowserPolicy()
        self._config = config or BrowserConfig()

    @property
    def policy(self) -> BrowserPolicy:
        return self._policy

    async def navigate_tab(
        self,
        tab: BrowserTab,
        url: str,
        timeout_seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Navigate tab to validated URL with bounded timeout and redirect policy checks."""
        # 1. Validate destination URL against SSRF and domain policies
        validated_url = self._policy.validate_url(url)
        timeout_ms = int((timeout_seconds or self._config.browser_navigation_timeout_seconds) * 1000)

        page = tab.page
        if not page:
            raise BrowserNavigationError(f"Tab '{tab.tab_id}' does not have an active page handle.")

        logger.info("Navigating tab '%s' to '%s'", tab.tab_id, validated_url)

        try:
            # If Playwright page is present
            if hasattr(page, "goto"):
                response = await page.goto(
                    validated_url,
                    timeout=timeout_ms,
                    wait_until="domcontentloaded",
                )
                final_url = page.url
                # If redirection occurred, validate final destination
                if final_url != validated_url:
                    self._policy.validate_redirect(validated_url, final_url)

                status_code = response.status if response else 200
                title = await page.title()
            else:
                # Simulated / mock navigation
                final_url = validated_url
                status_code = 200
                title = f"Page: {validated_url}"

            tab.url = final_url
            tab.title = title

            return {
                "url": final_url,
                "status_code": status_code,
                "title": title,
            }
        except BrowserSecurityError:
            raise
        except Exception as e:
            logger.error("Navigation error on tab '%s': %s", tab.tab_id, e)
            raise BrowserNavigationError(f"Failed to navigate to '{validated_url}': {e}") from e

    async def go_back(self, tab: BrowserTab) -> Dict[str, Any]:
        page = tab.page
        if not page:
            raise BrowserNavigationError("Active tab is not available.")
        if hasattr(page, "go_back"):
            await page.go_back(wait_until="domcontentloaded")
            tab.url = page.url
            tab.title = await page.title()
        return {"url": tab.url, "title": tab.title}

    async def go_forward(self, tab: BrowserTab) -> Dict[str, Any]:
        page = tab.page
        if not page:
            raise BrowserNavigationError("Active tab is not available.")
        if hasattr(page, "go_forward"):
            await page.go_forward(wait_until="domcontentloaded")
            tab.url = page.url
            tab.title = await page.title()
        return {"url": tab.url, "title": tab.title}

    async def reload_tab(self, tab: BrowserTab) -> Dict[str, Any]:
        page = tab.page
        if not page:
            raise BrowserNavigationError("Active tab is not available.")
        if hasattr(page, "reload"):
            await page.reload(wait_until="domcontentloaded")
            tab.url = page.url
            tab.title = await page.title()
        return {"url": tab.url, "title": tab.title}
