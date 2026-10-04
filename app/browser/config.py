"""BUDDY Browser Configuration.

Strongly typed configuration settings for browser automation, timeouts,
limits, download/upload quotas, and policy rules.
"""

from __future__ import annotations

from pathlib import Path
from typing import List
from pydantic import BaseModel, Field

from app.browser.models import BrowserEngine


class BrowserConfig(BaseModel):
    """Configuration options for browser automation subsystem."""

    browser_enabled: bool = Field(
        default=True,
        description="Whether browser automation subsystem is enabled",
    )
    browser_engine: BrowserEngine = Field(
        default=BrowserEngine.CHROMIUM,
        description="Default browser engine (chromium or edge)",
    )
    browser_headless: bool = Field(
        default=True,
        description="Run browser in headless mode",
    )
    browser_session_timeout_seconds: float = Field(
        default=300.0,
        ge=1.0,
        le=3600.0,
        description="Session inactivity timeout in seconds",
    )
    max_browser_session_duration: float = Field(
        default=300.0,
        ge=1.0,
        le=3600.0,
        description="Hard maximum session duration limit in seconds",
    )
    browser_action_timeout_seconds: float = Field(
        default=15.0,
        ge=1.0,
        le=120.0,
        description="Timeout for individual browser actions",
    )
    max_browser_action_timeout: float = Field(
        default=15.0,
        ge=1.0,
        le=120.0,
        description="Hard maximum timeout for any single browser action",
    )
    browser_navigation_timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=180.0,
        description="Timeout for page navigation and load states",
    )
    max_navigation_redirects: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum permitted HTTP redirect chain depth",
    )
    browser_max_tabs: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum concurrent open tabs per browser session",
    )
    max_browser_tabs: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Explicit limit: maximum concurrent open tabs per browser session",
    )
    browser_max_actions: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum browser actions allowed per task",
    )
    max_browser_actions_per_task: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Explicit limit: maximum browser actions allowed per task",
    )
    browser_max_download_size_mb: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Maximum download file size in megabytes",
    )
    max_browser_download_size_mb: int = Field(
        default=25,
        ge=1,
        le=100,
        description="Explicit limit: maximum download file size in megabytes",
    )
    browser_max_upload_size_mb: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum upload file size in megabytes",
    )
    max_browser_upload_size_mb: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Explicit limit: maximum upload file size in megabytes",
    )
    browser_max_page_text_chars: int = Field(
        default=20000,
        ge=50,
        le=100000,
        description="Maximum page text characters returned to AI",
    )
    max_page_text_chars: int = Field(
        default=20000,
        ge=50,
        le=100000,
        description="Explicit limit: maximum page text characters returned to AI",
    )
    browser_max_dom_nodes: int = Field(
        default=500,
        ge=50,
        le=2000,
        description="Maximum DOM elements inspected or returned",
    )
    max_dom_nodes: int = Field(
        default=500,
        ge=50,
        le=2000,
        description="Explicit limit: maximum DOM elements inspected or returned",
    )
    max_accessibility_nodes: int = Field(
        default=300,
        ge=20,
        le=1000,
        description="Explicit limit: maximum accessibility tree nodes parsed",
    )
    browser_min_target_confidence: float = Field(
        default=0.85,
        ge=0.5,
        le=1.0,
        description="Minimum target identification confidence threshold",
    )
    browser_allow_localhost: bool = Field(
        default=False,
        description="Allow navigation to localhost/127.0.0.1 (disabled by default for SSRF safety)",
    )
    browser_allow_private_networks: bool = Field(
        default=False,
        description="Allow navigation to private IP ranges (RFC 1918 / ULA)",
    )
    browser_allowed_domains: List[str] = Field(
        default_factory=list,
        description="Optional domain allowlist (empty allows any public domain)",
    )
    browser_blocked_domains: List[str] = Field(
        default_factory=list,
        description="Domain blocklist (always takes precedence over allowlist)",
    )
    browser_screenshot_enabled: bool = Field(
        default=True,
        description="Allow capturing in-memory screenshots",
    )
    browser_download_dir: Path = Field(
        default=Path("data/downloads"),
        description="Target directory for downloaded files",
    )

    model_config = {
        "extra": "forbid",
    }
