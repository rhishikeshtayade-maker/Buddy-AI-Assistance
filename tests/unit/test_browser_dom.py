"""Unit tests for Browser DOM inspection, fingerprinting, and form classification."""

import unittest

from app.browser.dom import (
    classify_input_sensitivity,
    compute_page_fingerprint,
    detect_captcha,
    detect_login_form,
)
from app.browser.models import FormField, FormFieldSensitivity


class TestBrowserDOM(unittest.TestCase):
    def test_classify_input_sensitivity(self):
        # Password
        self.assertEqual(
            classify_input_sensitivity("user_pwd", field_type="password"),
            FormFieldSensitivity.CREDENTIAL,
        )
        self.assertEqual(
            classify_input_sensitivity("login-password", field_type="text"),
            FormFieldSensitivity.CREDENTIAL,
        )

        # OTP / MFA
        self.assertEqual(
            classify_input_sensitivity("otp_token", field_type="text"),
            FormFieldSensitivity.CREDENTIAL,
        )
        self.assertEqual(
            classify_input_sensitivity("2fa_code", placeholder="Enter 6-digit code"),
            FormFieldSensitivity.CREDENTIAL,
        )

        # Payment
        self.assertEqual(
            classify_input_sensitivity("cc_num", placeholder="Card number"),
            FormFieldSensitivity.PAYMENT,
        )
        self.assertEqual(
            classify_input_sensitivity("cvv", placeholder="CVV"),
            FormFieldSensitivity.PAYMENT,
        )

        # Personal
        self.assertEqual(
            classify_input_sensitivity("user_email", field_type="email"),
            FormFieldSensitivity.PERSONAL,
        )
        self.assertEqual(
            classify_input_sensitivity("phone_number", field_type="tel"),
            FormFieldSensitivity.PERSONAL,
        )

        # Safe search
        self.assertEqual(
            classify_input_sensitivity("search_box", name="q", placeholder="Search docs"),
            FormFieldSensitivity.SAFE,
        )

    def test_page_fingerprint(self):
        fp1 = compute_page_fingerprint("https://example.com", "Title A", raw_html="<button id='b1'>Click</button>")
        fp2 = compute_page_fingerprint("https://example.com", "Title A", raw_html="<button id='b1'>Click</button>")
        fp3 = compute_page_fingerprint("https://example.com", "Title A", raw_html="<button id='b2'>Click</button>")
        fp4 = compute_page_fingerprint("https://example.com/other", "Title A", raw_html="<button id='b1'>Click</button>")

        self.assertEqual(fp1, fp2, "Identical pages must produce identical fingerprints")
        self.assertNotEqual(fp1, fp3, "Different elements must change fingerprint")
        self.assertNotEqual(fp1, fp4, "Different URLs must change fingerprint")

    def test_detect_captcha(self):
        self.assertTrue(detect_captcha("<div class='g-recaptcha'></div>"))
        self.assertTrue(detect_captcha("<iframe src='https://hcaptcha.com/widget'></iframe>"))
        self.assertTrue(detect_captcha("<div id='cf-turnstile-wrapper'></div>"))
        self.assertFalse(detect_captcha("<form><input type='text' name='q'></form>"))

    def test_detect_login_form(self):
        fields = [
            FormField(field_id="u", name="username", field_type="text"),
            FormField(field_id="p", name="password", field_type="password", sensitivity=FormFieldSensitivity.CREDENTIAL),
        ]
        self.assertTrue(detect_login_form(fields))

        search_fields = [
            FormField(field_id="q", name="query", field_type="text", sensitivity=FormFieldSensitivity.SAFE),
        ]
        self.assertFalse(detect_login_form(search_fields))


if __name__ == "__main__":
    unittest.main()
