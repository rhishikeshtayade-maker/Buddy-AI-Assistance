"""Unit tests for BrowserVerifier."""

import tempfile
import unittest
from pathlib import Path

from app.browser.models import BrowserTarget
from app.browser.verification import BrowserVerifier


class TestBrowserVerification(unittest.TestCase):
    def setUp(self):
        self.verifier = BrowserVerifier()

    def test_verify_navigation(self):
        # Successful match
        self.assertTrue(
            self.verifier.verify_navigation(
                expected_url="https://example.com/docs",
                current_url="https://example.com/docs/",
                status_code=200,
            )
        )
        # HTTP error status
        self.assertFalse(
            self.verifier.verify_navigation(
                expected_url="https://example.com",
                current_url="https://example.com",
                status_code=404,
            )
        )

    def test_verify_click(self):
        target = BrowserTarget(
            target_id="btn",
            page_url="https://example.com",
            page_fingerprint="fp1",
        )
        # URL change
        self.assertTrue(
            self.verifier.verify_click(
                target=target,
                initial_fingerprint="fp1",
                post_fingerprint="fp1",
                initial_url="https://example.com/1",
                post_url="https://example.com/2",
            )
        )
        # Fingerprint change
        self.assertTrue(
            self.verifier.verify_click(
                target=target,
                initial_fingerprint="fp1",
                post_fingerprint="fp2",
                initial_url="https://example.com",
                post_url="https://example.com",
            )
        )
        # Element state change
        self.assertTrue(
            self.verifier.verify_click(
                target=target,
                initial_fingerprint="fp1",
                post_fingerprint="fp1",
                initial_url="https://example.com",
                post_url="https://example.com",
                element_state_changed=True,
            )
        )
        # Empirical failure when no state mutation occurs
        self.assertFalse(
            self.verifier.verify_click(
                target=target,
                initial_fingerprint="fp1",
                post_fingerprint="fp1",
                initial_url="https://example.com",
                post_url="https://example.com",
                element_state_changed=False,
            )
        )

    def test_verify_typing(self):
        target = BrowserTarget(
            target_id="input1",
            page_url="https://example.com",
            page_fingerprint="fp1",
        )
        # Normal field
        self.assertTrue(
            self.verifier.verify_typing(
                target=target,
                expected_text="hello",
                actual_value="hello",
                is_sensitive=False,
            )
        )
        self.assertFalse(
            self.verifier.verify_typing(
                target=target,
                expected_text="hello",
                actual_value="other",
                is_sensitive=False,
            )
        )
        # Sensitive field (value redacted)
        self.assertTrue(
            self.verifier.verify_typing(
                target=target,
                expected_text="super_secret",
                actual_value="***REDACTED***",
                is_sensitive=True,
            )
        )

    def test_verify_download(self):
        with tempfile.NamedTemporaryFile() as tmp:
            tmp.write(b"SAMPLE DATA")
            tmp.flush()
            path = Path(tmp.name)
            self.assertTrue(self.verifier.verify_download(path, min_size=5))
            self.assertFalse(self.verifier.verify_download(path, min_size=100))

    def test_verify_upload(self):
        self.assertTrue(self.verifier.verify_upload(input_file_count=1, expected_count=1))
        self.assertFalse(self.verifier.verify_upload(input_file_count=0, expected_count=1))


if __name__ == "__main__":
    unittest.main()
