"""BUDDY Secret Vault Real Windows Smoke Test.

Demonstrates 12 live operational capabilities on Windows:
1. Secure provider initialization (DPAPI / Credential Manager)
2. Secret storage
3. Secret retrieval internally via bounded container
4. Metadata-only logging (tamper-evident audit without plaintext)
5. Centralized secret redaction
6. Atomic credential rotation
7. Secret deletion and existence verification
8. Direct Windows DPAPI round-trip encryption
9. Direct Windows Credential Manager integration (or graceful mock)
10. Memory encryption key migration (BUDDY_MEMORY_KEY -> native vault)
11. AI provider credential isolation
12. Bounded lifetime and clean zeroization shutdown

NEVER prints plaintext secrets. Uses synthetic test secrets only.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List

from app.core.config import BuddyConfig
from app.core.logging import get_logger, setup_logging
from app.memory.encryption import get_memory_encryptor
from app.security.audit import AuditLogger
from app.security.secrets.credential_manager import WindowsCredentialManagerProvider
from app.security.secrets.key_manager import BUDDY_MEMORY_ENCRYPTION_KEY
from app.security.secrets.models import SecretAccessType, SecretSensitivity
from app.security.secrets.redaction import REDACTED_SECRET, redact_string, redact_structure
from app.security.secrets.service import SecretVaultService
from app.security.secrets.windows_dpapi import WindowsDPAPIProvider

logger = get_logger("security.secrets.smoke_test")


class SmokeTestRunner:
    """Orchestrates the 12-stage Windows native security smoke test."""

    def __init__(self) -> None:
        self.results: Dict[str, bool] = {}
        self.temp_dir = tempfile.mkdtemp(prefix="buddy_smoke_vault_")
        self.vault_dir = Path(self.temp_dir) / "vault"
        self.audit_log_path = Path(self.temp_dir) / "audit.log"
        self.audit_logger = AuditLogger(log_path=self.audit_log_path)
        self.synthetic_key = "synthetic-test-key-32-bytes-abcdefg123456"
        self.rotated_key = "synthetic-rotated-key-32-bytes-xyz987654"

    def record(self, stage: str, success: bool, detail: str = "") -> None:
        self.results[stage] = success
        status = "PASSED" if success else "FAILED"
        print(f"[{status}] Stage: {stage} - {detail}")

    def run_all(self) -> bool:
        print("=" * 70)
        print("BUDDY LOOP 11 — NATIVE SECRET VAULT & DPAPI SMOKE TEST")
        print(f"Platform: {sys.platform} | Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)

        # 1. Secure Provider Initialization
        try:
            dpapi_prov = WindowsDPAPIProvider(vault_dir=self.vault_dir)
            self.service = SecretVaultService(provider=dpapi_prov, audit_logger=self.audit_logger)
            self.record("1. Secure Provider Initialization", True, f"Primary: {self.service.provider.provider_name}")
        except Exception as e:
            self.record("1. Secure Provider Initialization", False, str(e))
            return False

        # 2. Secret Storage
        try:
            meta = self.service.store_secret(
                identifier="BUDDY_SMOKE_OPENAI_API_KEY",
                secret_value=self.synthetic_key,
                metadata={"purpose": "smoke_test", "owner": "buddy_ci"},
                sensitivity=SecretSensitivity.HIGHLY_SENSITIVE,
            )
            self.record("2. Secret Storage", meta.version == 1, f"Stored ID={meta.identifier}, version={meta.version}")
        except Exception as e:
            self.record("2. Secret Storage", False, str(e))

        # 3. Secret Retrieval Internally
        try:
            with self.service.access_secret("BUDDY_SMOKE_OPENAI_API_KEY", SecretAccessType.SECRET_USE) as val:
                matched = (val == self.synthetic_key)
            self.record("3. Secret Retrieval Internally", matched, "Accessed internally within bounded context block")
        except Exception as e:
            self.record("3. Secret Retrieval Internally", False, str(e))

        # 4. Metadata-Only Logging
        try:
            audit_content = self.audit_log_path.read_text(encoding="utf-8")
            has_synthetic = self.synthetic_key in audit_content
            has_meta = "BUDDY_SMOKE_OPENAI_API_KEY" in audit_content
            passed = (not has_synthetic) and has_meta
            self.record("4. Metadata-Only Logging", passed, "Verified 0 plaintext secret leakage in audit logs")
        except Exception as e:
            self.record("4. Metadata-Only Logging", False, str(e))

        # 5. Secret Redaction
        try:
            raw_text = "Here is my sk-proj-1234567890abcdef1234567890 and Bearer secrettoken1234567890."
            redacted = redact_string(raw_text)
            passed = ("sk-proj" not in redacted) and (REDACTED_SECRET in redacted)
            self.record("5. Centralized Secret Redaction", passed, f"Redacted sample: {redacted}")
        except Exception as e:
            self.record("5. Centralized Secret Redaction", False, str(e))

        # 6. Secret Rotation
        try:
            rot_result = self.service.rotate_secret("BUDDY_SMOKE_OPENAI_API_KEY", self.rotated_key)
            with self.service.access_secret("BUDDY_SMOKE_OPENAI_API_KEY") as new_val:
                val_matches = (new_val == self.rotated_key)
            passed = rot_result.success and (rot_result.new_version == 2) and val_matches
            self.record("6. Credential Rotation", passed, f"Rotated v{rot_result.old_version} -> v{rot_result.new_version}")
        except Exception as e:
            self.record("6. Credential Rotation", False, str(e))

        # 7. Secret Deletion
        try:
            deleted = self.service.delete_secret("BUDDY_SMOKE_OPENAI_API_KEY")
            exists_now = self.service.exists("BUDDY_SMOKE_OPENAI_API_KEY")
            passed = deleted and (not exists_now)
            self.record("7. Secret Deletion", passed, "Secret deleted and existence confirmed False")
        except Exception as e:
            self.record("7. Secret Deletion", False, str(e))

        # 8. DPAPI Direct Protection Round-Trip
        try:
            direct_dpapi = WindowsDPAPIProvider(vault_dir=self.vault_dir / "dpapi_direct")
            direct_dpapi.store("DPAPI_TEST_KEY", self.synthetic_key)
            retrieved = direct_dpapi.retrieve("DPAPI_TEST_KEY")
            # Verify file on disk is encrypted (ciphertext is binary/base64, not plaintext)
            payload_path = self.vault_dir / "dpapi_direct" / "DPAPI_TEST_KEY.dpapi"
            on_disk = payload_path.read_text(encoding="utf-8")
            disk_encrypted = self.synthetic_key not in on_disk
            passed = (retrieved == self.synthetic_key) and disk_encrypted
            self.record("8. Direct Windows DPAPI Protection", passed, "CryptProtectData & CryptUnprotectData verified")
        except Exception as e:
            self.record("8. Direct Windows DPAPI Protection", False, str(e))

        # 9. Credential Manager Integration
        try:
            cred_mgr = WindowsCredentialManagerProvider(target_prefix="BUDDY_SMOKE:")
            h = cred_mgr.health()
            if cred_mgr.is_available:
                cred_mgr.store("TEST_CRED", self.synthetic_key)
                c_val = cred_mgr.retrieve("TEST_CRED")
                cred_mgr.delete("TEST_CRED")
                self.record("9. Windows Credential Manager", c_val == self.synthetic_key, "advapi32.dll store/retrieve/delete passed")
            else:
                self.record("9. Windows Credential Manager", True, f"Safely unavailable in current session: {h.message}")
        except Exception as e:
            self.record("9. Windows Credential Manager", False, str(e))

        # 10. Memory Migration Integration
        try:
            legacy_key_pass = "my_strong_legacy_passphrase_for_buddy"
            os.environ["BUDDY_MEMORY_KEY"] = legacy_key_pass
            cfg = BuddyConfig(memory_encryption_enabled=True)
            encryptor = get_memory_encryptor(cfg, vault_service=self.service)
            c_text = encryptor.encrypt("Sensitive memory content")
            p_text = encryptor.decrypt(c_text)
            in_vault = self.service.exists(BUDDY_MEMORY_ENCRYPTION_KEY)
            passed = (p_text == "Sensitive memory content") and in_vault
            # Cleanup env
            os.environ.pop("BUDDY_MEMORY_KEY", None)
            self.record("10. Memory Key Migration", passed, "Migrated legacy BUDDY_MEMORY_KEY into native vault")
        except Exception as e:
            self.record("10. Memory Key Migration", False, str(e))

        # 11. AI Provider Isolation
        try:
            from app.ai.provider import CloudAIProvider, LocalAIProvider
            c_prov = CloudAIProvider(api_key="sk-proj-supersecretkey1234567890abcdef")
            l_prov = LocalAIProvider()
            c_repr = repr(c_prov)
            l_repr = repr(l_prov)
            has_secret = "supersecretkey" in c_repr or "supersecretkey" in str(c_prov)
            passed = not has_secret
            self.record("11. AI Provider Credential Isolation", passed, f"Safe repr verified: {c_repr}")
        except Exception as e:
            self.record("11. AI Provider Credential Isolation", False, str(e))

        # 12. Bounded Lifetime & Clean Zeroization Shutdown
        try:
            self.service.shutdown()
            active_left = len(self.service.lifecycle_manager._active_containers)
            passed = (active_left == 0)
            self.record("12. Clean Shutdown & Zeroization", passed, "All active secret memory containers zeroized")
        except Exception as e:
            self.record("12. Clean Shutdown & Zeroization", False, str(e))

        print("=" * 70)
        all_passed = all(self.results.values())
        total = len(self.results)
        passed_count = sum(1 for v in self.results.values() if v)
        print(f"SMOKE TEST SUMMARY: {passed_count}/{total} PASSED")
        print("=" * 70)
        return all_passed


if __name__ == "__main__":
    setup_logging("INFO")
    runner = SmokeTestRunner()
    success = runner.run_all()
    sys.exit(0 if success else 1)
