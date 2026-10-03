"""Unit tests for Loop 0: Project Foundation."""

import importlib
import io
import sys
from pathlib import Path
import unittest

from app import __version__, __product__, __tagline__
from app.main import main


class TestProjectFoundation(unittest.TestCase):
    """Test suite verifying base package foundation, security rules, and metadata."""

    def test_product_identity(self):
        """Verify core product name, version, and branding tagline."""
        self.assertEqual(__product__, "BUDDY")
        self.assertEqual(__version__, "0.1.0")
        self.assertIn("Your Voice. Your Laptop. Your Control.", __tagline__)

    def test_package_imports(self):
        """Verify that all core architectural packages can be imported cleanly."""
        packages = [
            "app",
            "app.core",
            "app.voice",
            "app.ai",
            "app.agent",
            "app.tools",
            "app.security",
            "app.memory",
            "app.vision",
            "app.automation",
            "app.ui",
            "app.ui.components",
            "app.storage",
        ]
        for pkg in packages:
            mod = importlib.import_module(pkg)
            self.assertIsNotNone(mod, f"Failed to import package: {pkg}")

    def test_gitignore_security_rules(self):
        """Verify that .gitignore enforces Rule 1 & Rule 6 (no secrets, keys, or logs)."""
        gitignore_path = Path(__file__).resolve().parents[2] / ".gitignore"
        self.assertTrue(gitignore_path.exists(), ".gitignore must exist in root")
        content = gitignore_path.read_text(encoding="utf-8")
        
        self.assertIn(".env", content)
        self.assertIn("*.key", content)
        self.assertIn("*.pem", content)
        self.assertIn("master.key", content)
        self.assertIn("audit_logs/", content)

    def test_env_example_template(self):
        """Verify that .env.example contains necessary config keys and no hard-coded secrets."""
        env_example_path = Path(__file__).resolve().parents[2] / ".env.example"
        self.assertTrue(env_example_path.exists(), ".env.example must exist in root")
        content = env_example_path.read_text(encoding="utf-8")
        
        self.assertIn("BUDDY_ENV", content)
        self.assertIn("BUDDY_AI_PROVIDER", content)
        self.assertIn("BUDDY_MASTER_KEY_STORAGE", content)
        self.assertIn("BUDDY_WAKE_WORD", content)

        # Must NOT have any real secrets populated
        self.assertNotIn("sk-", content)
        self.assertTrue(
            "password" not in content.lower() or "password-derived" in content.lower(),
            "Found raw password references in template",
        )

    def test_main_entry_point(self):
        """Verify app.main() executes successfully and prints banner."""
        captured_stdout = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = captured_stdout
            exit_code = main()
        finally:
            sys.stdout = old_stdout

        self.assertEqual(exit_code, 0)
        self.assertIn("BUDDY", captured_stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
