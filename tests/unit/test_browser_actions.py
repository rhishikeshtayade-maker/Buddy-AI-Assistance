"""Unit tests for BrowserAction validation, key allowlists, and executor."""

import unittest
from unittest.mock import AsyncMock, MagicMock

from app.browser.actions import (
    classify_action_risk,
    inspect_field_for_typing,
    validate_key_name,
)
from app.browser.elements import TargetResolver
from app.browser.exceptions import (
    AmbiguousTargetError,
    BrowserSecurityError,
    LowConfidenceTargetError,
    StaleTargetError,
)
from app.browser.executor import BrowserExecutor
from app.browser.models import (
    BrowserAction,
    BrowserActionType,
    BrowserRiskLevel,
    BrowserTarget,
    FormFieldSensitivity,
)
from app.browser.session import BrowserSession


class TestBrowserActions(unittest.IsolatedAsyncioTestCase):
    def test_key_allowlist(self):
        # Explicit test for every single permitted key required by Loop 9
        permitted_keys = [
            ("ENTER", "Enter"),
            ("ESC", "Escape"),
            ("TAB", "Tab"),
            ("BACKSPACE", "Backspace"),
            ("SPACE", " "),
            ("ARROW_UP", "ArrowUp"),
            ("ARROW_DOWN", "ArrowDown"),
            ("ARROW_LEFT", "ArrowLeft"),
            ("ARROW_RIGHT", "ArrowRight"),
            ("HOME", "Home"),
            ("END", "End"),
            ("PAGE_UP", "PageUp"),
            ("PAGE_DOWN", "PageDown"),
        ]
        for raw_key, expected_mapped in permitted_keys:
            with self.subTest(permitted_key=raw_key):
                self.assertEqual(validate_key_name(raw_key), expected_mapped)
                # Case-insensitive validation
                self.assertEqual(validate_key_name(raw_key.lower()), expected_mapped)

        # Prohibited keys that must be strictly rejected
        prohibited = [
            "CTRL+C",
            "ALT+F4",
            "F12",
            "WINDOWS",
            "PRINTSCREEN",
            "COMMAND",
            "INSERT",
            "F1",
            "F5",
            "META",
            "CONTROL",
            "ALT",
            "SHIFT",
            "SUPER",
        ]
        for key in prohibited:
            with self.subTest(prohibited_key=key):
                with self.assertRaises(BrowserSecurityError):
                    validate_key_name(key)

    def test_inspect_field_for_typing(self):
        # Safe input
        safe_target = BrowserTarget(
            target_id="search_box",
            accessible_name="Search",
            target_type="text",
            page_url="https://example.com",
            page_fingerprint="fp1",
        )
        sens, risk = inspect_field_for_typing(safe_target, "test query")
        self.assertEqual(sens, FormFieldSensitivity.SAFE)
        self.assertEqual(risk, BrowserRiskLevel.LOW)

        # Credential input
        pwd_target = BrowserTarget(
            target_id="user_password",
            target_type="password",
            page_url="https://example.com",
            page_fingerprint="fp1",
        )
        sens, risk = inspect_field_for_typing(pwd_target, "secret123")
        self.assertEqual(sens, FormFieldSensitivity.CREDENTIAL)
        self.assertEqual(risk, BrowserRiskLevel.HIGH)

    def test_target_resolver(self):
        resolver = TargetResolver(min_confidence=0.85)

        # Good candidate
        candidates = [
            {
                "target_id": "btn_submit",
                "role": "button",
                "accessible_name": "Submit Form",
                "text": "Submit Form",
                "selector": "#btn-submit",
            }
        ]
        target = resolver.resolve_target(candidates, "https://example.com", "fp1", query="Submit Form")
        self.assertEqual(target.target_id, "btn_submit")
        self.assertGreaterEqual(target.confidence, 0.90)

        # Low confidence
        low_candidates = [{"target_id": "div_1", "role": "div", "confidence": 0.50}]
        with self.assertRaises(LowConfidenceTargetError):
            resolver.resolve_target(low_candidates, "https://example.com", "fp1")

        # Ambiguous matches
        ambig_candidates = [
            {"target_id": "b1", "role": "button", "accessible_name": "Click", "text": "Click"},
            {"target_id": "b2", "role": "button", "accessible_name": "Click", "text": "Click"},
        ]
        with self.assertRaises(AmbiguousTargetError):
            resolver.resolve_target(ambig_candidates, "https://example.com", "fp1", query="Click")

    def test_target_staleness(self):
        resolver = TargetResolver()
        target = BrowserTarget(
            target_id="btn",
            page_url="https://example.com",
            page_fingerprint="fp_original",
        )

        # Valid when fingerprint matches
        resolver.validate_target_staleness(target, current_fingerprint="fp_original", current_url="https://example.com")

        # Stale when fingerprint changes
        with self.assertRaises(StaleTargetError):
            resolver.validate_target_staleness(target, current_fingerprint="fp_mutated", current_url="https://example.com")

        # Stale when URL changes
        with self.assertRaises(StaleTargetError):
            resolver.validate_target_staleness(target, current_fingerprint="fp_original", current_url="https://other.com")

    async def test_executor_action_dispatch(self):
        executor = BrowserExecutor()

        # Mock page
        mock_page = MagicMock()
        mock_page.url = "https://example.com"
        mock_page.click = AsyncMock()

        mock_session = MagicMock()
        mock_session.touch = MagicMock()
        mock_tab = MagicMock()
        mock_tab.page = mock_page
        mock_tab.url = "https://example.com"
        mock_tab.fingerprint = "fp1"
        mock_session.get_active_tab.return_value = mock_tab
        mock_session.tab_manager.get_tab.return_value = mock_tab

        action = BrowserAction(
            action_type=BrowserActionType.CLICK,
            session_id="s1",
            arguments={"selector": "#btn"},
        )

        res = await executor.execute_action(mock_session, action)
        self.assertTrue(res.success)
        self.assertTrue(res.verification)
        mock_page.click.assert_awaited_once_with("#btn", timeout=5000)

    async def test_executor_verification_failure(self):
        executor = BrowserExecutor()

        mock_page = MagicMock()
        mock_page.url = "https://example.com"
        mock_page.click = AsyncMock()

        mock_session = MagicMock()
        mock_session.touch = MagicMock()
        mock_tab = MagicMock()
        mock_tab.page = mock_page
        mock_tab.url = "https://example.com"
        mock_tab.fingerprint = "fp1"
        mock_session.get_active_tab.return_value = mock_tab
        mock_session.tab_manager.get_tab.return_value = mock_tab

        action = BrowserAction(
            action_type=BrowserActionType.CLICK,
            session_id="s_fail",
            arguments={"selector": "#btn", "simulate_verification_failure": True},
        )

        res = await executor.execute_action(mock_session, action)
        self.assertFalse(res.success)
        self.assertFalse(res.verification)
        self.assertEqual(res.status, "verification_failed")

    async def test_bounded_wait_operations(self):
        executor = BrowserExecutor()

        mock_page = MagicMock()
        mock_page.wait_for_selector = AsyncMock()
        mock_page.wait_for_load_state = AsyncMock()
        mock_page.wait_for_url = AsyncMock()

        mock_session = MagicMock()
        mock_session.session_id = "s_wait"
        mock_session.touch = MagicMock()
        mock_tab = MagicMock()
        mock_tab.page = mock_page
        mock_session.get_active_tab.return_value = mock_tab
        mock_session.tab_manager.get_tab.return_value = mock_tab

        # 1. wait_for_selector
        res = await executor.execute_action(
            mock_session,
            BrowserAction(
                action_type=BrowserActionType.WAIT,
                session_id="s_wait",
                arguments={"operation": "wait_for_selector", "selector": "#my-elem", "timeout_seconds": 2.0},
            ),
        )
        self.assertTrue(res.success)
        mock_page.wait_for_selector.assert_awaited_once_with("#my-elem", timeout=2000, state="visible")

        # 2. wait_for_load_state
        res2 = await executor.execute_action(
            mock_session,
            BrowserAction(
                action_type=BrowserActionType.WAIT,
                session_id="s_wait",
                arguments={"operation": "wait_for_load_state", "load_state": "networkidle", "timeout_seconds": 1.5},
            ),
        )
        self.assertTrue(res2.success)
        mock_page.wait_for_load_state.assert_awaited_once_with("networkidle", timeout=1500)

        # 3. Invalid load state rejected
        res3 = await executor.execute_action(
            mock_session,
            BrowserAction(
                action_type=BrowserActionType.WAIT,
                session_id="s_wait",
                arguments={"operation": "wait_for_load_state", "load_state": "arbitrary_eval"},
            ),
        )
        self.assertFalse(res3.success)
        self.assertEqual(res3.status, "failed")

    async def test_max_actions_limit_enforced(self):
        from app.browser.config import BrowserConfig
        cfg = BrowserConfig(max_browser_actions_per_task=2)
        executor = BrowserExecutor(config=cfg)

        mock_session = MagicMock()
        mock_session.session_id = "s_limit"
        mock_session.touch = MagicMock()
        mock_tab = MagicMock()
        mock_tab.page = MagicMock()
        mock_session.get_active_tab.return_value = mock_tab

        action = BrowserAction(
            action_type=BrowserActionType.WAIT,
            session_id="s_limit",
            arguments={"operation": "duration", "seconds": 0.01},
        )

        # 1st action: OK
        res1 = await executor.execute_action(mock_session, action)
        self.assertTrue(res1.success)

        # 2nd action: OK
        res2 = await executor.execute_action(mock_session, action)
        self.assertTrue(res2.success)

        # 3rd action: exceeds limit -> BrowserSecurityError
        with self.assertRaises(BrowserSecurityError):
            await executor.execute_action(mock_session, action)


if __name__ == "__main__":
    unittest.main()
