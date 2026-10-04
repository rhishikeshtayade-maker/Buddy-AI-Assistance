"""Unit tests for Browser models.

Tests strong typing, enum values, default configurations, extra='forbid' constraints,
and confidence bounds.
"""

import unittest
from pydantic import ValidationError

from app.browser.models import (
    BrowserAction,
    BrowserActionResult,
    BrowserActionType,
    BrowserEngine,
    BrowserPageInfo,
    BrowserRiskLevel,
    BrowserSessionStatus,
    BrowserTabStatus,
    BrowserTarget,
    FormField,
    FormFieldSensitivity,
)


class TestBrowserModels(unittest.TestCase):
    def test_enums(self):
        self.assertEqual(BrowserEngine.CHROMIUM.value, "chromium")
        self.assertEqual(BrowserEngine.EDGE.value, "edge")
        self.assertEqual(BrowserSessionStatus.CREATED.value, "created")
        self.assertEqual(BrowserSessionStatus.RUNNING.value, "running")
        self.assertEqual(BrowserTabStatus.ACTIVE.value, "active")
        self.assertEqual(BrowserActionType.CLICK.value, "click")
        self.assertEqual(BrowserRiskLevel.SAFE, 0)
        self.assertEqual(BrowserRiskLevel.CRITICAL, 4)
        self.assertEqual(FormFieldSensitivity.CREDENTIAL.value, "credential")

    def test_browser_target_validation(self):
        target = BrowserTarget(
            target_id="btn_1",
            selector="#submit",
            role="button",
            accessible_name="Submit",
            page_url="https://example.com",
            page_fingerprint="fp123",
            confidence=0.95,
        )
        self.assertEqual(target.target_id, "btn_1")
        self.assertEqual(target.confidence, 0.95)

        # Extra forbidden
        with self.assertRaises(ValidationError):
            BrowserTarget(
                target_id="btn_1",
                page_url="https://example.com",
                page_fingerprint="fp123",
                unknown_field="extra",
            )

        # Confidence bounds [0.0, 1.0]
        with self.assertRaises(ValidationError):
            BrowserTarget(
                target_id="btn_1",
                page_url="https://example.com",
                page_fingerprint="fp123",
                confidence=1.5,
            )
        with self.assertRaises(ValidationError):
            BrowserTarget(
                target_id="btn_1",
                page_url="https://example.com",
                page_fingerprint="fp123",
                confidence=-0.1,
            )

    def test_browser_action_validation(self):
        action = BrowserAction(
            action_type=BrowserActionType.NAVIGATE,
            session_id="sess_1",
            arguments={"url": "https://example.com"},
        )
        self.assertIsNotNone(action.action_id)
        self.assertEqual(action.action_type, BrowserActionType.NAVIGATE)

        # Extra forbidden
        with self.assertRaises(ValidationError):
            BrowserAction(
                action_type=BrowserActionType.NAVIGATE,
                session_id="sess_1",
                extra_param="forbidden",
            )

    def test_browser_action_result(self):
        res = BrowserActionResult(
            action_id="act_1",
            success=True,
            verification=True,
            result={"status": "ok"},
        )
        self.assertTrue(res.success)
        self.assertTrue(res.verification)

        with self.assertRaises(ValidationError):
            BrowserActionResult(
                action_id="act_1",
                invalid_extra="fail",
            )

    def test_form_field_model(self):
        field = FormField(
            field_id="pwd",
            name="password",
            field_type="password",
            sensitivity=FormFieldSensitivity.CREDENTIAL,
            required=True,
        )
        self.assertEqual(field.sensitivity, FormFieldSensitivity.CREDENTIAL)
        self.assertTrue(field.required)

        with self.assertRaises(ValidationError):
            FormField(field_id="pwd", unapproved="extra")

    def test_browser_page_info(self):
        info = BrowserPageInfo(
            session_id="s1",
            tab_id="t1",
            url="https://example.com",
            title="Example Domain",
            page_fingerprint="abcd1234",
            is_sensitive=False,
            has_captcha=False,
            has_login=False,
            tabs_count=1,
        )
        self.assertEqual(info.title, "Example Domain")
        with self.assertRaises(ValidationError):
            BrowserPageInfo(
                session_id="s1",
                tab_id="t1",
                url="https://example.com",
                title="Example",
                page_fingerprint="abcd",
                extra_field=True,
            )


if __name__ == "__main__":
    unittest.main()
