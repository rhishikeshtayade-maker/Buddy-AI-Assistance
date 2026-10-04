"""Unit tests for Browser DownloadManager."""

import tempfile
import unittest
from pathlib import Path

from app.browser.config import BrowserConfig
from app.browser.downloads import DownloadManager
from app.browser.exceptions import BrowserDownloadError


class TestBrowserDownloads(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config = BrowserConfig(
            browser_download_dir=Path(self.temp_dir.name),
            browser_max_download_size_mb=2,
        )
        self.mgr = DownloadManager(self.config)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_sanitize_filename(self):
        self.assertEqual(self.mgr.sanitize_filename("report.pdf"), "report.pdf")
        self.assertEqual(self.mgr.sanitize_filename("../../../etc/passwd"), "etc_passwd")
        self.assertEqual(self.mgr.sanitize_filename("my:report<test>.doc"), "my_report_test_.doc")
        self.assertEqual(self.mgr.sanitize_filename(""), "download.bin")

    def test_validate_download_target_containment(self):
        dest = self.mgr.validate_download_target("document.pdf")
        self.assertTrue(dest.is_relative_to(Path(self.temp_dir.name)))

    def test_dangerous_extension_rejection(self):
        dangerous = ["malware.exe", "script.bat", "run.ps1", "setup.msi", "trojan.scr", "hack.vbs"]
        for fname in dangerous:
            with self.subTest(fname=fname):
                with self.assertRaises(BrowserDownloadError):
                    self.mgr.validate_download_target(fname)

    def test_file_size_validation(self):
        # Create normal file
        good_file = Path(self.temp_dir.name) / "good.txt"
        good_file.write_bytes(b"A" * 1024)
        self.assertEqual(self.mgr.validate_file_size(good_file), 1024)

        # Create oversized file (> 2 MB)
        big_file = Path(self.temp_dir.name) / "huge.txt"
        big_file.write_bytes(b"B" * (3 * 1024 * 1024))
        with self.assertRaises(BrowserDownloadError):
            self.mgr.validate_file_size(big_file)


if __name__ == "__main__":
    unittest.main()
