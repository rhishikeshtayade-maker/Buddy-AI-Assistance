"""Unit tests for Browser UploadManager."""

import tempfile
import unittest
from pathlib import Path

from app.browser.config import BrowserConfig
from app.browser.exceptions import BrowserUploadError
from app.browser.uploads import UploadManager
from app.security.path_policy import PathPolicy


class TestBrowserUploads(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.temp_dir.name).resolve()
        self.policy = PathPolicy(allowed_roots=[self.root_path])
        self.config = BrowserConfig(browser_max_upload_size_mb=2)
        self.mgr = UploadManager(self.config, self.policy)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_valid_upload(self):
        valid_file = self.root_path / "document.txt"
        valid_file.write_text("Hello World")

        validated = self.mgr.validate_upload_file(valid_file)
        self.assertEqual(validated, valid_file)

    def test_credential_file_rejection(self):
        secret_file = self.root_path / "passwords.txt"
        secret_file.write_text("secret_password=123")
        with self.assertRaises(BrowserUploadError):
            self.mgr.validate_upload_file(secret_file)

    def test_executable_file_rejection(self):
        exe_file = self.root_path / "malicious.exe"
        exe_file.write_bytes(b"MZ123")
        with self.assertRaises(BrowserUploadError):
            self.mgr.validate_upload_file(exe_file)

        # Prohibited scripts
        for ext in (".bat", ".cmd", ".ps1", ".vbs"):
            script_file = self.root_path / f"script{ext}"
            script_file.write_text("echo test")
            with self.subTest(ext=ext):
                with self.assertRaises(BrowserUploadError):
                    self.mgr.validate_upload_file(script_file)

    def test_private_key_and_env_rejection(self):
        # .pem, .key, .env, id_rsa
        for fname in ("id_rsa", "server.key", "cert.pem", ".env", "id_ed25519"):
            sec_file = self.root_path / fname
            sec_file.write_text("PRIVATE_KEY_CONTENT")
            with self.subTest(file=fname):
                with self.assertRaises(BrowserUploadError):
                    self.mgr.validate_upload_file(sec_file)

    def test_path_traversal_rejection(self):
        outside_path = Path("C:/Windows/System32/drivers/etc/hosts")
        with self.assertRaises(BrowserUploadError):
            self.mgr.validate_upload_file(outside_path)

    def test_oversized_upload_rejection(self):
        big_file = self.root_path / "large_data.bin"
        big_file.write_bytes(b"0" * (3 * 1024 * 1024))
        with self.assertRaises(BrowserUploadError):
            self.mgr.validate_upload_file(big_file)

    def test_sensitive_file_classification(self):
        self.assertTrue(self.mgr.is_sensitive_upload(Path("resume.pdf")))
        self.assertTrue(self.mgr.is_sensitive_upload(Path("data.xlsx")))
        self.assertFalse(self.mgr.is_sensitive_upload(Path("image.png")))


if __name__ == "__main__":
    unittest.main()
