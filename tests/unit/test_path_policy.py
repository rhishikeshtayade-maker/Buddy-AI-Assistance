"""Unit tests for Centralized Path Security Policy."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.exceptions import PathSecurityError
from app.security.path_policy import PathPolicy


class TestPathPolicy(unittest.TestCase):
    """Test filesystem isolation and traversal defenses in PathPolicy."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sandbox = Path(self.temp_dir.name).resolve()
        self.policy = PathPolicy(allowed_roots=[self.sandbox])

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_valid_path_within_sandbox_allowed(self) -> None:
        test_file = self.sandbox / "notes.txt"
        resolved = self.policy.validate_path(test_file)
        self.assertEqual(resolved, test_file)
        self.assertTrue(self.policy.is_path_allowed(test_file))

    def test_relative_path_within_sandbox_allowed(self) -> None:
        sub_dir = self.sandbox / "sub"
        sub_dir.mkdir()
        test_file = sub_dir / "doc.txt"
        resolved = self.policy.validate_path(str(test_file))
        self.assertEqual(resolved, test_file)

    def test_path_traversal_dotdot_rejected(self) -> None:
        traversal = self.sandbox / ".." / "outside.txt"
        with self.assertRaises(PathSecurityError):
            self.policy.validate_path(traversal)
        self.assertFalse(self.policy.is_path_allowed(traversal))

    def test_path_traversal_string_rejected(self) -> None:
        traversal_str = str(self.sandbox) + "/../../etc/passwd"
        with self.assertRaises(PathSecurityError):
            self.policy.validate_path(traversal_str)

    def test_windows_device_names_rejected(self) -> None:
        device_paths = [
            self.sandbox / "CON",
            self.sandbox / "PRN.txt",
            self.sandbox / "AUX",
            self.sandbox / "NUL",
            self.sandbox / "COM1",
            self.sandbox / "LPT1.dat",
        ]
        for dp in device_paths:
            with self.assertRaises(PathSecurityError):
                self.policy.validate_path(dp)

    def test_unc_and_device_prefixes_rejected(self) -> None:
        unc_paths = [
            r"\\server\share\file.txt",
            r"//server/share/file.txt",
            r"\\?\C:\secret.txt",
            r"\\.\PhysicalDrive0",
        ]
        for unc in unc_paths:
            with self.assertRaises(PathSecurityError):
                self.policy.validate_path(unc)

    def test_protected_files_rejected(self) -> None:
        forbidden = [
            self.sandbox / ".env",
            self.sandbox / ".env.production",
            self.sandbox / ".ssh" / "id_rsa",
            self.sandbox / "secret.key",
            self.sandbox / "server.pem",
            self.sandbox / "credentials",
            self.sandbox / ".git" / "config",
        ]
        for f in forbidden:
            with self.assertRaises(PathSecurityError):
                self.policy.validate_path(f)

    def test_protected_system_paths_rejected(self) -> None:
        system_paths = [
            r"C:\Windows\System32\cmd.exe",
            r"C:\Program Files\test.exe",
            r"/etc/shadow",
            r"/bin/sh",
        ]
        for sp in system_paths:
            with self.assertRaises(PathSecurityError):
                self.policy.validate_path(sp)


if __name__ == "__main__":
    unittest.main()
