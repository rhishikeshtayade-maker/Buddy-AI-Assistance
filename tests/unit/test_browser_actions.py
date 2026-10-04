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
        # Valid allowlisted keys
        self.assertEqual(validate_key_name("ENTER"), "Enter")
        self.assertEqual(validate_key_name("Tab"), "Tab")
        self.assertEqual(validate_key_name("escape"), "Escape")
        self.assertEqual(validate_key_name("ARROW_DOWN"), "ArrowDown")

        # Prohibited keys
        prohibited = ["CTRL+C", "ALT+F4", "F12", "WINDOWS", "PRINTSCREEN", "COMMAND"]
        for key in prohibited:
            with self.subTest(key=key):
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


if __name__ == "__main__":
    unittest.main()
