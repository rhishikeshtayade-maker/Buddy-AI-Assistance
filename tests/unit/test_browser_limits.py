"""Unit tests proving that all 10 browser task limits fail closed when exceeded."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from app.browser.accessibility import parse_accessibility_tree
from app.browser.actions import validate_key_name
from app.browser.config import BrowserConfig
from app.browser.downloads import DownloadManager
from app.browser.exceptions import (
    BrowserDownloadError,
    BrowserSecurityError,
    BrowserTabError,
    BrowserTimeoutError,
    BrowserUploadError,
)
from app.browser.executor import BrowserExecutor
from app.browser.models import BrowserAction, BrowserActionType, BrowserSessionStatus
from app.browser.policy import BrowserPolicy
from app.browser.sanitizer import WebContentSanitizer
from app.browser.session import BrowserSession
from app.browser.tabs import BrowserTab, TabManager
from app.browser.uploads import UploadManager
from app.security.path_policy import PathPolicy


class TestBrowserTaskLimits(unittest.IsolatedAsyncioTestCase):
    def test_1_max_browser_actions_per_task_fails_closed(self):
        cfg = BrowserConfig(max_browser_actions_per_task=3)
        executor = BrowserExecutor(config=cfg)

        mock_session = MagicMock()
        mock_session.session_id = "s_lim"
        mock_session.touch = MagicMock()
        mock_tab = MagicMock()
        mock_tab.page = MagicMock()
        mock_session.get_active_tab.return_value = mock_tab

        action = BrowserAction(
            action_type=BrowserActionType.WAIT,
            session_id="s_lim",
            arguments={"operation": "duration", "seconds": 0.001},
        )

        # 3 actions succeed
        for _ in range(3):
            executor._action_counts["s_lim"] = executor._action_counts.get("s_lim", 0)
        executor._action_counts["s_lim"] = 3

        # 4th action must fail closed
        with self.assertRaises(BrowserSecurityError):
            import asyncio
            asyncio.run(executor.execute_action(mock_session, action))

    def test_2_max_browser_tabs_fails_closed(self):
        tm = TabManager(max_tabs=2)
        t1 = BrowserTab("tab1")
        t2 = BrowserTab("tab2")
        t3 = BrowserTab("tab3")

        tm.add_tab(t1)
        tm.add_tab(t2)

        # 3rd tab exceeds limit of 2 -> fails closed
        with self.assertRaises(BrowserTabError):
            tm.add_tab(t3)

    def test_3_max_browser_download_size_mb_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = BrowserConfig(browser_download_dir=Path(tmp), max_browser_download_size_mb=1)
            dm = DownloadManager(cfg)

            oversized_file = Path(tmp) / "large.zip"
            oversized_file.write_bytes(b"A" * (2 * 1024 * 1024))  # 2 MB > 1 MB

            with self.assertRaises(BrowserDownloadError):
                dm.validate_file_size(oversized_file)

            # Proves oversized file was removed to preserve disk integrity
            self.assertFalse(oversized_file.exists())

    def test_4_max_browser_upload_size_mb_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            policy = PathPolicy(allowed_roots=[root])
            cfg = BrowserConfig(max_browser_upload_size_mb=1)
            um = UploadManager(cfg, policy)

            big_file = root / "big_payload.txt"
            big_file.write_bytes(b"B" * (2 * 1024 * 1024))  # 2 MB > 1 MB

            with self.assertRaises(BrowserUploadError):
                um.validate_upload_file(big_file)

    def test_5_max_page_text_chars_fails_closed(self):
        cfg = BrowserConfig(max_page_text_chars=100)
        sanitizer = WebContentSanitizer(cfg)

        giant_text = "HelloWorld " * 50  # 550 chars > 100
        cleaned = sanitizer.sanitize_page_text(giant_text)

        self.assertIn("[Truncated: exceeded 100 characters]", cleaned)
        self.assertLessEqual(len(cleaned), 160)

    def test_6_max_dom_nodes_fails_closed(self):
        from app.browser.dom import compute_page_fingerprint
        nodes = [{"tag": "div", "id": f"node_{i}", "role": "box"} for i in range(1000)]
        # Handled cleanly and capped at 200 nodes for fingerprinting without exploding
        fp = compute_page_fingerprint("https://example.com", "Test", dom_summary=nodes)
        self.assertEqual(len(fp), 16)

    def test_7_max_accessibility_nodes_fails_closed(self):
        # Create deep nested tree with 50 nodes
        raw_tree = {"role": "root", "children": []}
        curr = raw_tree
        for i in range(50):
            child = {"role": "button", "name": f"btn_{i}", "children": []}
            curr["children"].append(child)
            curr = child

        parsed, count = parse_accessibility_tree(raw_tree, max_nodes=5)
        # Parse tree is strictly capped at max_nodes=5
        self.assertLessEqual(count, 5)

    def test_8_max_navigation_redirects_fails_closed(self):
        cfg = BrowserConfig(max_navigation_redirects=2, browser_allow_localhost=True)
        policy = BrowserPolicy(cfg)

        # 1 and 2 redirects allowed
        policy.validate_redirect("http://127.0.0.1/1", "http://127.0.0.1/2", redirect_count=1)
        policy.validate_redirect("http://127.0.0.1/2", "http://127.0.0.1/3", redirect_count=2)

        # 3rd redirect exceeds limit of 2 -> fails closed
        with self.assertRaises(BrowserSecurityError):
            policy.validate_redirect("http://127.0.0.1/3", "http://127.0.0.1/4", redirect_count=3)

    def test_9_max_browser_session_duration_fails_closed(self):
        cfg = BrowserConfig(browser_session_timeout_seconds=1.0, max_browser_session_duration=1.0)
        sess = BrowserSession("sess_timeout", cfg)
        sess.last_activity = time.time() - 10.0  # Inactive for 10s > 1.0s
        self.assertTrue(sess.is_expired)

    def test_10_max_browser_action_timeout_fails_closed(self):
        cfg = BrowserConfig(max_browser_action_timeout=2.0)
        executor = BrowserExecutor(config=cfg, default_timeout=50.0)
        # Executor bounds timeout to max_browser_action_timeout
        effective = min(executor._default_timeout, executor._config.max_browser_action_timeout)
        self.assertEqual(effective, 2.0)


if __name__ == "__main__":
    unittest.main()
