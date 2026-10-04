"""Unit tests for BrowserPolicy.

Tests scheme validation, SSRF defenses, cloud metadata blocking,
strict domain matching, and redirect destination validation.
"""

import unittest

from app.browser.config import BrowserConfig
from app.browser.exceptions import BrowserSecurityError
from app.browser.policy import BrowserPolicy


class TestBrowserPolicy(unittest.TestCase):
    def setUp(self):
        self.config = BrowserConfig(
            browser_enabled=True,
            browser_allow_localhost=False,
            browser_allow_private_networks=False,
        )
        self.policy = BrowserPolicy(self.config)

    def test_valid_public_urls(self):
        self.assertEqual(
            self.policy.validate_url("https://www.example.com"),
            "https://www.example.com",
        )
        self.assertEqual(
            self.policy.validate_url("http://python.org/doc"),
            "http://python.org/doc",
        )

    def test_rejected_forbidden_schemes(self):
        forbidden = [
            "javascript:alert(1)",
            "file:///C:/Windows/System32/calc.exe",
            "data:text/html,<h1>Hello</h1>",
            "vbscript:msgbox",
            "chrome://settings",
            "edge://version",
            "about:blank",
            "ftp://ftp.example.com",
        ]
        for url in forbidden:
            with self.subTest(url=url):
                with self.assertRaises(BrowserSecurityError):
                    self.policy.validate_url(url)

    def test_ssrf_ip_blocking_by_default(self):
        blocked_ips = [
            "http://127.0.0.1:8080",
            "http://0.0.0.0",
            "http://10.0.0.1/admin",
            "http://172.16.0.5/api",
            "http://192.168.1.1/router",
            "http://169.254.169.254/latest/meta-data",  # Cloud metadata
            "http://100.100.100.100",                   # Alibaba metadata
        ]
        for url in blocked_ips:
            with self.subTest(url=url):
                with self.assertRaises(BrowserSecurityError):
                    self.policy.validate_url(url)

    def test_ssrf_hostnames_blocking(self):
        blocked_hosts = [
            "http://localhost:3000",
            "http://metadata.google.internal/computeMetadata/v1/",
            "http://server.local",
            "http://internal.corp",
            "http://router.lan",
        ]
        for url in blocked_hosts:
            with self.subTest(url=url):
                with self.assertRaises(BrowserSecurityError):
                    self.policy.validate_url(url)

    def test_localhost_permitted_when_explicitly_configured(self):
        dev_config = BrowserConfig(browser_allow_localhost=True)
        dev_policy = BrowserPolicy(dev_config)
        self.assertEqual(
            dev_policy.validate_url("http://127.0.0.1:8080/test"),
            "http://127.0.0.1:8080/test",
        )
        self.assertEqual(
            dev_policy.validate_url("http://localhost:5000"),
            "http://localhost:5000",
        )

    def test_domain_allowlist_enforcement(self):
        cfg = BrowserConfig(browser_allowed_domains=["example.com", "*.trusted.org"])
        policy = BrowserPolicy(cfg)

        # Allowed
        self.assertEqual(policy.validate_url("https://example.com"), "https://example.com")
        self.assertEqual(policy.validate_url("https://sub.example.com"), "https://sub.example.com")
        self.assertEqual(policy.validate_url("https://api.trusted.org"), "https://api.trusted.org")

        # Rejected (not in allowlist or naive substring spoof)
        with self.assertRaises(BrowserSecurityError):
            policy.validate_url("https://evil-example.com")  # Substring spoof rejected!
        with self.assertRaises(BrowserSecurityError):
            policy.validate_url("https://notexample.com")
        with self.assertRaises(BrowserSecurityError):
            policy.validate_url("https://google.com")

    def test_domain_blocklist_enforcement(self):
        cfg = BrowserConfig(browser_blocked_domains=["malicious.com", "*.tracker.net"])
        policy = BrowserPolicy(cfg)

        with self.assertRaises(BrowserSecurityError):
            policy.validate_url("https://malicious.com/payload")
        with self.assertRaises(BrowserSecurityError):
            policy.validate_url("https://sub.tracker.net/collect")

        # Other domains allowed
        self.assertEqual(policy.validate_url("https://example.com"), "https://example.com")

    def test_redirect_revalidation(self):
        cfg = BrowserConfig(browser_allowed_domains=["example.com"])
        policy = BrowserPolicy(cfg)

        # Redirect within allowed domain
        valid = policy.validate_redirect("https://example.com/login", "https://example.com/home")
        self.assertEqual(valid, "https://example.com/home")

        # Redirect crossing to unapproved or malicious domain
        with self.assertRaises(BrowserSecurityError):
            policy.validate_redirect("https://example.com/login", "https://evil.com/phish")

    def test_redirect_chain_limit_enforcement(self):
        cfg = BrowserConfig(max_navigation_redirects=3, browser_allow_localhost=True)
        policy = BrowserPolicy(cfg)

        # 1 to 3 redirects: OK
        self.assertEqual(
            policy.validate_redirect("http://127.0.0.1:8000/1", "http://127.0.0.1:8000/2", redirect_count=1),
            "http://127.0.0.1:8000/2",
        )
        self.assertEqual(
            policy.validate_redirect("http://127.0.0.1:8000/2", "http://127.0.0.1:8000/3", redirect_count=3),
            "http://127.0.0.1:8000/3",
        )

        # 4th redirect exceeds max_navigation_redirects (3)
        with self.assertRaises(BrowserSecurityError):
            policy.validate_redirect("http://127.0.0.1:8000/3", "http://127.0.0.1:8000/4", redirect_count=4)


if __name__ == "__main__":
    unittest.main()
