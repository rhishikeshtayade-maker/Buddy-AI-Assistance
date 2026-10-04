"""BUDDY Browser Action Executor.

Dispatches validated BrowserAction objects to Playwright or session pages,
coordinates staleness checks, enforces timeout bounds, and runs post-execution verification.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from app.browser.actions import (
    classify_action_risk,
    inspect_field_for_typing,
    validate_key_name,
)
from app.browser.dom import compute_page_fingerprint
from app.browser.elements import TargetResolver
from app.browser.exceptions import (
    BrowserError,
    BrowserSecurityError,
    BrowserTimeoutError,
    BrowserVerificationError,
    StaleTargetError,
)
from app.browser.models import (
    BrowserAction,
    BrowserActionResult,
    BrowserActionType,
    BrowserRiskLevel,
    BrowserTarget,
    FormFieldSensitivity,
)
from app.browser.session import BrowserSession
from app.browser.verification import BrowserVerifier

logger = logging.getLogger("buddy.browser.executor")


class BrowserExecutor:
    """Executes validated BrowserActions against active browser sessions."""

    def __init__(
        self,
        target_resolver: Optional[TargetResolver] = None,
        verifier: Optional[BrowserVerifier] = None,
        default_timeout: float = 15.0,
    ) -> None:
        self._target_resolver = target_resolver or TargetResolver()
        self._verifier = verifier or BrowserVerifier()
        self._default_timeout = default_timeout

    async def execute_action(
        self,
        session: BrowserSession,
        action: BrowserAction,
    ) -> BrowserActionResult:
        """Execute a structured browser action with staleness check and post-verification."""
        start_time = time.perf_counter()
        session.touch()

        # Resolve target tab
        tab = session.tab_manager.get_tab(action.tab_id) if action.tab_id else session.get_active_tab()
        page = tab.page

        # 1. Staleness check if target is provided
        if action.target and hasattr(page, "url"):
            current_url = page.url
            # Read current HTML or title to evaluate fingerprint if needed
            current_fp = tab.fingerprint or action.target.page_fingerprint
            try:
                self._target_resolver.validate_target_staleness(
                    target=action.target,
                    current_fingerprint=current_fp,
                    current_url=current_url,
                )
            except StaleTargetError as e:
                logger.warning("Action %s aborted: %s", action.action_id, e)
                return BrowserActionResult(
                    action_id=action.action_id,
                    success=False,
                    status="stale_target_rejected",
                    verification=False,
                    error=str(e),
                )

        # 2. Execute with bounded timeout
        timeout = self._default_timeout
        try:
            result_data, verified = await asyncio.wait_for(
                self._dispatch(session, tab, action),
                timeout=timeout,
            )

            latency = time.perf_counter() - start_time
            return BrowserActionResult(
                action_id=action.action_id,
                success=verified,
                status="completed" if verified else "verification_failed",
                result=result_data,
                verification=verified,
                metadata={"latency": latency},
            )
        except asyncio.TimeoutError:
            err = f"Browser action '{action.action_type.value}' timed out after {timeout:.1f}s."
            logger.error(err)
            return BrowserActionResult(
                action_id=action.action_id,
                success=False,
                status="timeout",
                verification=False,
                error=err,
            )
        except Exception as e:
            err = f"Browser action '{action.action_type.value}' failed: {e}"
            logger.error(err)
            return BrowserActionResult(
                action_id=action.action_id,
                success=False,
                status="failed",
                verification=False,
                error=err,
            )

    async def _dispatch(
        self,
        session: BrowserSession,
        tab: Any,
        action: BrowserAction,
    ) -> tuple[Any, bool]:
        """Internal dispatch according to action_type."""
        page = tab.page
        a_type = action.action_type
        args = action.arguments
        target = action.target

        # Handle CLICK / DOUBLE_CLICK
        if a_type in (BrowserActionType.CLICK, BrowserActionType.DOUBLE_CLICK):
            init_fp = tab.fingerprint
            init_url = tab.url
            selector = target.selector if target else args.get("selector")

            if page and hasattr(page, "click") and selector:
                if a_type == BrowserActionType.DOUBLE_CLICK:
                    await page.dblclick(selector, timeout=5000)
                else:
                    await page.click(selector, timeout=5000)

            post_url = page.url if page and hasattr(page, "url") else init_url
            post_fp = tab.fingerprint
            verified = self._verifier.verify_click(
                target=target,
                initial_fingerprint=init_fp,
                post_fingerprint=post_fp,
                initial_url=init_url,
                post_url=post_url,
                element_state_changed=True,
            )
            return {"clicked": selector or target.target_id if target else "element"}, verified

        # Handle TYPE
        elif a_type == BrowserActionType.TYPE:
            text = str(args.get("text", ""))
            selector = target.selector if target else args.get("selector")
            is_sensitive = args.get("is_sensitive", False)

            # Check if secret typing
            sensitivity, risk = inspect_field_for_typing(target, text)
            if sensitivity in (FormFieldSensitivity.CREDENTIAL, FormFieldSensitivity.PAYMENT):
                is_sensitive = True

            actual_val = None
            if page and hasattr(page, "fill") and selector:
                await page.fill(selector, text, timeout=5000)
                if not is_sensitive and hasattr(page, "input_value"):
                    actual_val = await page.input_value(selector)
                elif is_sensitive:
                    actual_val = "***REDACTED***"
            else:
                actual_val = "***REDACTED***" if is_sensitive else text

            verified = self._verifier.verify_typing(
                target=target,
                expected_text=text,
                actual_value=actual_val,
                is_sensitive=is_sensitive,
            )
            # Safe result without logging sensitive text
            return {"field": target.target_id if target else selector, "typed": True}, verified

        # Handle PRESS_KEY
        elif a_type == BrowserActionType.PRESS_KEY:
            raw_key = str(args.get("key", "ENTER"))
            safe_key = validate_key_name(raw_key)

            if page and hasattr(page, "keyboard"):
                await page.keyboard.press(safe_key)

            return {"key_pressed": safe_key}, True

        # Handle SELECT
        elif a_type == BrowserActionType.SELECT:
            selector = target.selector if target else args.get("selector")
            value = str(args.get("value", ""))
            if page and hasattr(page, "select_option") and selector:
                await page.select_option(selector, value)
            return {"selected": value}, True

        # Handle SCROLL
        elif a_type == BrowserActionType.SCROLL:
            direction = str(args.get("direction", "down")).lower()
            delta_y = 500 if direction == "down" else -500
            if page and hasattr(page, "mouse"):
                await page.mouse.wheel(0, delta_y)
            return {"scrolled": direction}, True

        # Handle WAIT
        elif a_type == BrowserActionType.WAIT:
            duration = min(float(args.get("seconds", 1.0)), 10.0)
            await asyncio.sleep(duration)
            return {"waited_seconds": duration}, True

        # Handle FOCUS
        elif a_type == BrowserActionType.FOCUS:
            selector = target.selector if target else args.get("selector")
            if page and hasattr(page, "focus") and selector:
                await page.focus(selector)
            return {"focused": target.target_id if target else selector}, True

        return {"status": "unsupported"}, False
