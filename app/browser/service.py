"""BUDDY Browser Subsystem Service.

High-level controlled facade for secure browser automation.
Encapsulates session lifecycle, tab management, navigation, extraction,
element identification, safe interaction, and event emission.
NEVER exposes raw Playwright objects or handles to the AI planner.
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.browser.actions import classify_action_risk, validate_key_name
from app.browser.browser import BrowserManager
from app.browser.config import BrowserConfig
from app.browser.dom import (
    compute_page_fingerprint,
    detect_captcha,
    detect_login_form,
)
from app.browser.downloads import DownloadManager
from app.browser.elements import TargetResolver
from app.browser.events import (
    BrowserActionExecutedEvent,
    BrowserActionRequestedEvent,
    BrowserActionVerifiedEvent,
    BrowserCaptchaDetectedEvent,
    BrowserDownloadCompletedEvent,
    BrowserDownloadStartedEvent,
    BrowserNavigationCompletedEvent,
    BrowserNavigationStartedEvent,
    BrowserPromptInjectionDetectedEvent,
    BrowserSensitiveFieldDetectedEvent,
    BrowserSessionClosedEvent,
    BrowserSessionCreatedEvent,
    BrowserSessionStartedEvent,
    BrowserTabClosedEvent,
    BrowserTabCreatedEvent,
    BrowserTaskPausedEvent,
    BrowserUploadCompletedEvent,
    BrowserUploadRequestedEvent,
)
from app.browser.exceptions import (
    BrowserError,
    BrowserNavigationError,
    BrowserSecurityError,
    BrowserSessionError,
    BrowserTabError,
    BrowserTargetError,
    BrowserTimeoutError,
)
from app.browser.executor import BrowserExecutor
from app.browser.extraction import ExtractedPageContent, PageExtractor
from app.browser.models import (
    BrowserAction,
    BrowserActionResult,
    BrowserActionType,
    BrowserPageInfo,
    BrowserRiskLevel,
    BrowserSessionStatus,
    BrowserTabStatus,
    BrowserTarget,
    FormField,
    FormFieldSensitivity,
)
from app.browser.navigation import NavigationManager
from app.browser.policy import BrowserPolicy
from app.browser.sanitizer import WebContentSanitizer
from app.browser.screenshots import BrowserScreenshot, ScreenshotManager
from app.browser.session import BrowserSession
from app.browser.tabs import BrowserTab
from app.browser.uploads import UploadManager
from app.browser.verification import BrowserVerifier
from app.core.events import EventBus
from app.security.path_policy import PathPolicy

logger = logging.getLogger("buddy.browser.service")


class BrowserService:
    """Unified service interface for all browser operations."""

    def __init__(
        self,
        config: Optional[BrowserConfig] = None,
        event_bus: Optional[EventBus] = None,
        path_policy: Optional[PathPolicy] = None,
    ) -> None:
        self._config = config or BrowserConfig()
        self._event_bus = event_bus
        self._policy = BrowserPolicy(self._config)
        self._browser_manager = BrowserManager(self._config)
        self._navigation = NavigationManager(self._policy, self._config)
        self._sanitizer = WebContentSanitizer(self._config)
        self._extractor = PageExtractor(self._config, self._sanitizer)
        self._target_resolver = TargetResolver(min_confidence=self._config.browser_min_target_confidence)
        self._verifier = BrowserVerifier()
        self._screenshot_mgr = ScreenshotManager(self._config)
        self._download_mgr = DownloadManager(self._config)
        self._upload_mgr = UploadManager(self._config, path_policy)
        self._executor = BrowserExecutor(
            self._target_resolver,
            self._verifier,
            upload_mgr=self._upload_mgr,
            config=self._config,
            default_timeout=self._config.browser_action_timeout_seconds,
        )

        self._sessions: Dict[str, BrowserSession] = {}

    @property
    def config(self) -> BrowserConfig:
        return self._config

    @property
    def policy(self) -> BrowserPolicy:
        return self._policy

    async def _publish(self, event: Any) -> None:
        if self._event_bus:
            try:
                await self._event_bus.publish(event)
            except Exception as e:
                logger.error("Failed to publish browser event %s: %s", type(event).__name__, e)

    def get_session(self, session_id: Optional[str] = None) -> BrowserSession:
        """Retrieve existing active session or fail."""
        if not session_id:
            # Return first active non-expired session if any
            for s in self._sessions.values():
                if not s.is_expired and s.status == BrowserSessionStatus.RUNNING:
                    return s
            raise BrowserSessionError("No active browser session found. Call browser.open first.")

        session = self._sessions.get(session_id)
        if not session:
            raise BrowserSessionError(f"Browser session '{session_id}' not found.")
        if session.is_expired:
            session.status = BrowserSessionStatus.CLOSED
            raise BrowserTimeoutError(f"Browser session '{session_id}' has expired.")
        return session

    async def open_session(self, session_id: Optional[str] = None) -> BrowserSession:
        """Create and launch a new isolated browser session."""
        session = BrowserSession(
            session_id=session_id,
            config=self._config,
            browser_manager=self._browser_manager,
        )
        self._sessions[session.session_id] = session

        await self._publish(
            BrowserSessionCreatedEvent(
                session_id=session.session_id,
                engine=self._config.browser_engine.value,
                headless=self._config.browser_headless,
            )
        )

        await session.start()

        await self._publish(
            BrowserSessionStartedEvent(
                session_id=session.session_id,
                browser_version="1.0",
            )
        )

        return session

    async def close_session(self, session_id: str, reason: str = "normal") -> bool:
        """Close an active session and release its resources."""
        session = self._sessions.get(session_id)
        if not session:
            return False

        await session.close()
        del self._sessions[session_id]

        await self._publish(
            BrowserSessionClosedEvent(
                session_id=session_id,
                reason=reason,
            )
        )
        return True

    async def new_tab(self, session_id: Optional[str] = None, url: str = "about:blank") -> BrowserTab:
        if url and url != "about:blank":
            self._policy.validate_url(url)
        session = self.get_session(session_id)
        tab = await session.new_tab(url)
        await self._publish(
            BrowserTabCreatedEvent(
                session_id=session.session_id,
                tab_id=tab.tab_id,
            )
        )
        if url and url != "about:blank":
            await self.navigate(url=url, session_id=session.session_id, tab_id=tab.tab_id)
        return tab

    async def close_tab(self, session_id: Optional[str] = None, tab_id: Optional[str] = None) -> None:
        session = self.get_session(session_id)
        target_tab = session.tab_manager.get_tab(tab_id) if tab_id else session.get_active_tab()
        await session.close_tab(target_tab.tab_id)
        await self._publish(
            BrowserTabClosedEvent(
                session_id=session.session_id,
                tab_id=target_tab.tab_id,
            )
        )

    async def switch_tab(self, tab_id: str, session_id: Optional[str] = None) -> BrowserTab:
        session = self.get_session(session_id)
        return await session.switch_tab(tab_id)

    async def navigate(
        self,
        url: str,
        session_id: Optional[str] = None,
        tab_id: Optional[str] = None,
    ) -> BrowserPageInfo:
        """Controlled navigation to URL with SSRF checks, prompt injection scanning, and fingerprinting."""
        session = self.get_session(session_id)
        tab = session.tab_manager.get_tab(tab_id) if tab_id else session.get_active_tab()

        await self._publish(
            BrowserNavigationStartedEvent(
                session_id=session.session_id,
                tab_id=tab.tab_id,
                url=url,
            )
        )

        nav_result = await self._navigation.navigate_tab(
            tab=tab,
            url=url,
            timeout_seconds=self._config.browser_navigation_timeout_seconds,
        )

        # Post-navigation page inspection
        page_info = await self.inspect_page(session_id=session.session_id, tab_id=tab.tab_id)

        await self._publish(
            BrowserNavigationCompletedEvent(
                session_id=session.session_id,
                tab_id=tab.tab_id,
                url=page_info.url,
                status_code=page_info.status_code,
                title=page_info.title,
                fingerprint=page_info.page_fingerprint,
            )
        )

        # Check for CAPTCHA
        if page_info.has_captcha:
            await self._publish(
                BrowserCaptchaDetectedEvent(
                    session_id=session.session_id,
                    url=page_info.url,
                    captcha_type="challenge_detected",
                )
            )
            await self._publish(
                BrowserTaskPausedEvent(
                    session_id=session.session_id,
                    reason="CAPTCHA challenge detected; human interaction required.",
                )
            )

        return page_info

    async def back(self, session_id: Optional[str] = None, tab_id: Optional[str] = None) -> BrowserPageInfo:
        session = self.get_session(session_id)
        tab = session.tab_manager.get_tab(tab_id) if tab_id else session.get_active_tab()
        await self._navigation.go_back(tab)
        return await self.inspect_page(session_id=session.session_id, tab_id=tab.tab_id)

    async def forward(self, session_id: Optional[str] = None, tab_id: Optional[str] = None) -> BrowserPageInfo:
        session = self.get_session(session_id)
        tab = session.tab_manager.get_tab(tab_id) if tab_id else session.get_active_tab()
        await self._navigation.go_forward(tab)
        return await self.inspect_page(session_id=session.session_id, tab_id=tab.tab_id)

    async def reload(self, session_id: Optional[str] = None, tab_id: Optional[str] = None) -> BrowserPageInfo:
        session = self.get_session(session_id)
        tab = session.tab_manager.get_tab(tab_id) if tab_id else session.get_active_tab()
        await self._navigation.reload_tab(tab)
        return await self.inspect_page(session_id=session.session_id, tab_id=tab.tab_id)

    async def inspect_page(
        self,
        session_id: Optional[str] = None,
        tab_id: Optional[str] = None,
    ) -> BrowserPageInfo:
        """Inspect current page state, compute fingerprint, and detect sensitive forms/CAPTCHA."""
        session = self.get_session(session_id)
        tab = session.tab_manager.get_tab(tab_id) if tab_id else session.get_active_tab()
        page = tab.page

        raw_html = ""
        title = tab.title
        url = tab.url

        if page and hasattr(page, "content"):
            try:
                raw_html = await page.content()
                title = await page.title()
                url = page.url
            except Exception:
                pass

        fp = compute_page_fingerprint(url=url, title=title, raw_html=raw_html)
        tab.fingerprint = fp
        tab.url = url
        tab.title = title

        has_captcha = detect_captcha(raw_html)

        # Inspect forms for login / sensitive fields
        is_sensitive = False
        has_login = False
        if page and hasattr(page, "locator"):
            try:
                pw_count = await page.locator("input[type='password']").count()
                if pw_count > 0:
                    is_sensitive = True
                    has_login = True
            except Exception:
                pass

        return BrowserPageInfo(
            session_id=session.session_id,
            tab_id=tab.tab_id,
            url=url,
            title=title,
            page_fingerprint=fp,
            is_sensitive=is_sensitive,
            has_captcha=has_captcha,
            has_login=has_login,
            tabs_count=len(session.tab_manager.list_tabs()),
        )

    async def find_element(
        self,
        query: str,
        role: Optional[str] = None,
        session_id: Optional[str] = None,
        tab_id: Optional[str] = None,
    ) -> BrowserTarget:
        """Discover an interactive element on the active page and resolve a confidence-scored BrowserTarget."""
        session = self.get_session(session_id)
        tab = session.tab_manager.get_tab(tab_id) if tab_id else session.get_active_tab()
        page = tab.page

        current_url = tab.url
        current_fp = tab.fingerprint or compute_page_fingerprint(current_url, tab.title)

        candidates: List[Dict[str, Any]] = []

        if page and hasattr(page, "locator"):
            # Try role locator first
            if role:
                loc = page.get_by_role(role, name=query)
                count = await loc.count()
                for i in range(min(count, 5)):
                    candidates.append({
                        "target_id": f"{role}_{query}_{i}",
                        "selector": f"{role}:has-text('{query}')",
                        "role": role,
                        "accessible_name": query,
                        "text": query,
                    })

            # Try text locator
            loc_text = page.get_by_text(query)
            count = await loc_text.count()
            for i in range(min(count, 5)):
                candidates.append({
                    "target_id": f"elem_{query}_{i}",
                    "selector": f"text='{query}'",
                    "text": query,
                })

            # Try standard CSS selector if query looks like one
            if any(c in query for c in ("#", ".", "[", ">")):
                try:
                    loc_css = page.locator(query)
                    if await loc_css.count() > 0:
                        candidates.append({
                            "target_id": f"css_{query}",
                            "selector": query,
                            "id": query.lstrip("#"),
                        })
                except Exception:
                    pass

        # If offline or simulated page
        if not candidates:
            candidates.append({
                "target_id": f"target_{uuid.uuid4().hex[:6]}",
                "selector": query if any(c in query for c in ("#", ".", "[")) else f"button:has-text('{query}')",
                "role": role or "button",
                "accessible_name": query,
                "text": query,
                "confidence": 0.85,
            })

        target = self._target_resolver.resolve_target(
            candidate_matches=candidates,
            page_url=current_url,
            current_fingerprint=current_fp,
            query=query,
        )

        return target

    async def click(
        self,
        target: Optional[BrowserTarget] = None,
        selector: Optional[str] = None,
        session_id: Optional[str] = None,
        tab_id: Optional[str] = None,
    ) -> BrowserActionResult:
        session = self.get_session(session_id)
        action = BrowserAction(
            action_type=BrowserActionType.CLICK,
            target=target,
            arguments={"selector": selector} if selector else {},
            session_id=session.session_id,
            tab_id=tab_id,
            risk_level=BrowserRiskLevel.LOW,
        )

        await self._publish(
            BrowserActionRequestedEvent(
                action_id=action.action_id,
                session_id=session.session_id,
                action_type=action.action_type.value,
                target_id=target.target_id if target else selector,
                risk_level=action.risk_level.name,
            )
        )

        result = await self._executor.execute_action(session, action)

        await self._publish(
            BrowserActionExecutedEvent(
                action_id=action.action_id,
                session_id=session.session_id,
                action_type=action.action_type.value,
                latency=result.metadata.get("latency", 0.0),
            )
        )
        await self._publish(
            BrowserActionVerifiedEvent(
                action_id=action.action_id,
                session_id=session.session_id,
                action_type=action.action_type.value,
                verified=result.verification,
            )
        )
        return result

    async def double_click(
        self,
        target: Optional[BrowserTarget] = None,
        selector: Optional[str] = None,
        session_id: Optional[str] = None,
        tab_id: Optional[str] = None,
    ) -> BrowserActionResult:
        session = self.get_session(session_id)
        action = BrowserAction(
            action_type=BrowserActionType.DOUBLE_CLICK,
            target=target,
            arguments={"selector": selector} if selector else {},
            session_id=session.session_id,
            tab_id=tab_id,
            risk_level=BrowserRiskLevel.LOW,
        )
        return await self._executor.execute_action(session, action)

    async def type_text(
        self,
        text: str,
        target: Optional[BrowserTarget] = None,
        selector: Optional[str] = None,
        is_sensitive: bool = False,
        session_id: Optional[str] = None,
        tab_id: Optional[str] = None,
    ) -> BrowserActionResult:
        session = self.get_session(session_id)

        # Notify if sensitive field detected
        if is_sensitive or (target and "pass" in target.target_id.lower()):
            await self._publish(
                BrowserSensitiveFieldDetectedEvent(
                    session_id=session.session_id,
                    field_id=target.target_id if target else selector or "input",
                    field_type="password",
                    sensitivity="credential",
                )
            )

        action = BrowserAction(
            action_type=BrowserActionType.TYPE,
            target=target,
            arguments={"text": text, "selector": selector, "is_sensitive": is_sensitive},
            session_id=session.session_id,
            tab_id=tab_id,
            risk_level=BrowserRiskLevel.HIGH if is_sensitive else BrowserRiskLevel.LOW,
        )
        return await self._executor.execute_action(session, action)

    async def press_key(
        self,
        key: str,
        session_id: Optional[str] = None,
        tab_id: Optional[str] = None,
    ) -> BrowserActionResult:
        session = self.get_session(session_id)
        action = BrowserAction(
            action_type=BrowserActionType.PRESS_KEY,
            arguments={"key": key},
            session_id=session.session_id,
            tab_id=tab_id,
            risk_level=BrowserRiskLevel.LOW,
        )
        return await self._executor.execute_action(session, action)

    async def select_option(
        self,
        value: str,
        target: Optional[BrowserTarget] = None,
        selector: Optional[str] = None,
        session_id: Optional[str] = None,
        tab_id: Optional[str] = None,
    ) -> BrowserActionResult:
        session = self.get_session(session_id)
        action = BrowserAction(
            action_type=BrowserActionType.SELECT,
            target=target,
            arguments={"value": value, "selector": selector},
            session_id=session.session_id,
            tab_id=tab_id,
            risk_level=BrowserRiskLevel.LOW,
        )
        return await self._executor.execute_action(session, action)

    async def scroll(
        self,
        direction: str = "down",
        session_id: Optional[str] = None,
        tab_id: Optional[str] = None,
    ) -> BrowserActionResult:
        session = self.get_session(session_id)
        action = BrowserAction(
            action_type=BrowserActionType.SCROLL,
            arguments={"direction": direction},
            session_id=session.session_id,
            tab_id=tab_id,
            risk_level=BrowserRiskLevel.SAFE,
        )
        return await self._executor.execute_action(session, action)

    async def wait(
        self,
        operation: str = "duration",
        selector: Optional[str] = None,
        url: Optional[str] = None,
        load_state: Optional[str] = "load",
        timeout_seconds: Optional[float] = None,
        seconds: float = 1.0,
        session_id: Optional[str] = None,
        tab_id: Optional[str] = None,
    ) -> BrowserActionResult:
        session = self.get_session(session_id)
        effective_timeout = timeout_seconds if timeout_seconds is not None else seconds
        action = BrowserAction(
            action_type=BrowserActionType.WAIT,
            arguments={
                "operation": operation,
                "selector": selector,
                "url": url,
                "load_state": load_state,
                "timeout_seconds": effective_timeout,
                "seconds": effective_timeout,
            },
            session_id=session.session_id,
            tab_id=tab_id,
            risk_level=BrowserRiskLevel.SAFE,
        )
        return await self._executor.execute_action(session, action)

    async def extract_text(
        self,
        session_id: Optional[str] = None,
        tab_id: Optional[str] = None,
        max_chars: Optional[int] = None,
    ) -> ExtractedPageContent:
        """Extract visible page text, sanitize and wrap in security tags."""
        session = self.get_session(session_id)
        tab = session.tab_manager.get_tab(tab_id) if tab_id else session.get_active_tab()
        page = tab.page

        raw_text = ""
        if page and hasattr(page, "inner_text"):
            try:
                raw_text = await page.inner_text("body")
            except Exception:
                pass
        elif not raw_text:
            raw_text = f"Content of {tab.title} at {tab.url}"

        content = self._extractor.process_extracted_text(
            url=tab.url,
            title=tab.title,
            raw_text=raw_text,
            max_chars=max_chars,
        )

        if content.detected_injections:
            await self._publish(
                BrowserPromptInjectionDetectedEvent(
                    session_id=session.session_id,
                    url=tab.url,
                    pattern=",".join(content.detected_injections),
                    snippet=raw_text[:200],
                )
            )

        return content

    async def screenshot(
        self,
        session_id: Optional[str] = None,
        tab_id: Optional[str] = None,
    ) -> BrowserScreenshot:
        """Capture in-memory screenshot of active tab."""
        session = self.get_session(session_id)
        tab = session.tab_manager.get_tab(tab_id) if tab_id else session.get_active_tab()
        page = tab.page

        page_info = await self.inspect_page(session.session_id, tab.tab_id)
        self._screenshot_mgr.validate_screenshot_permitted(page_info.is_sensitive)

        img_bytes = b""
        if page and hasattr(page, "screenshot"):
            img_bytes = await page.screenshot(type="png", full_page=False)
        else:
            # Fallback 1x1 png for test mode
            img_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"

        return self._screenshot_mgr.wrap_screenshot_bytes(
            image_bytes=img_bytes,
            is_sensitive_page=page_info.is_sensitive,
        )

    async def download(
        self,
        url_or_target: str,
        suggested_filename: str = "download.bin",
        session_id: Optional[str] = None,
        tab_id: Optional[str] = None,
    ) -> Path:
        """Download file to sandboxed download directory with size and extension validation."""
        session = self.get_session(session_id)
        dest_path = self._download_mgr.validate_download_target(suggested_filename)

        await self._publish(
            BrowserDownloadStartedEvent(
                session_id=session.session_id,
                url=url_or_target,
                suggested_filename=suggested_filename,
            )
        )

        tab = session.tab_manager.get_tab(tab_id) if tab_id else session.get_active_tab()
        page = tab.page

        if page and hasattr(page, "expect_download"):
            # Trigger download via click or navigation
            async with page.expect_download() as download_info:
                if url_or_target.startswith(("http://", "https://")):
                    await page.goto(url_or_target)
                else:
                    await page.click(url_or_target)
            download = await download_info.value
            await download.save_as(str(dest_path))
        else:
            # Simulate or direct write
            dest_path.write_bytes(b"DATA" * 10)

        file_size = self._download_mgr.validate_file_size(dest_path)

        await self._publish(
            BrowserDownloadCompletedEvent(
                session_id=session.session_id,
                filename=dest_path.name,
                file_size_bytes=file_size,
            )
        )

        return dest_path

    async def upload(
        self,
        file_path: str,
        target: Optional[BrowserTarget] = None,
        selector: Optional[str] = None,
        session_id: Optional[str] = None,
        tab_id: Optional[str] = None,
    ) -> BrowserActionResult:
        """Upload validated local file to browser file input element through BrowserExecutor."""
        session = self.get_session(session_id)
        validated_file = self._upload_mgr.validate_upload_file(file_path)

        await self._publish(
            BrowserUploadRequestedEvent(
                session_id=session.session_id,
                filepath=str(validated_file),
                file_size_bytes=validated_file.stat().st_size,
            )
        )

        action = BrowserAction(
            action_type=BrowserActionType.UPLOAD,
            target=target,
            arguments={"file_path": str(validated_file), "selector": selector},
            session_id=session.session_id,
            tab_id=tab_id,
            risk_level=BrowserRiskLevel.MODERATE,
        )

        result = await self._executor.execute_action(session, action)

        if result.success:
            await self._publish(
                BrowserUploadCompletedEvent(
                    session_id=session.session_id,
                    filename=validated_file.name,
                    target_id=target.target_id if target else selector or "input[type='file']",
                )
            )

        return result

    async def shutdown(self) -> None:
        """Close all open sessions and stop browser engine."""
        for sid in list(self._sessions.keys()):
            try:
                await self.close_session(sid, reason="shutdown")
            except Exception:
                pass
        await self._browser_manager.stop()
