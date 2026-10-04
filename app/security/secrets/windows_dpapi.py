"""BUDDY Windows Data Protection API (DPAPI) Provider.

Provides native OS-backed hardware/user-keyed encryption using Windows crypt32.dll.
Protects secrets at rest tied to the Windows user account with zero plaintext persistence.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.health import HealthCheckResult, HealthStatus
from app.core.logging import get_logger
from app.security.secrets.exceptions import DPAPIError, SecretNotFoundError, SecretStorageError
from app.security.secrets.models import SecretMetadata, SecretRotationResult, SecretSensitivity
from app.security.secrets.provider import SecretProvider

logger = get_logger("security.secrets.dpapi")

# Windows DPAPI Constants
CRYPTPROTECT_UI_FORBIDDEN = 0x01
CRYPTPROTECT_LOCAL_MACHINE = 0x04


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


class WindowsDPAPIProvider(SecretProvider):
    """Secure secret vault backed by Windows Data Protection API (DPAPI)."""

    def __init__(
        self,
        vault_dir: Optional[Path] = None,
        use_machine_scope: bool = False,
        entropy: Optional[bytes] = b"buddy_dpapi_entropy_v1",
    ) -> None:
        self._vault_dir = vault_dir or Path("data/vault/dpapi")
        self._vault_dir.mkdir(parents=True, exist_ok=True)
        self._flags = CRYPTPROTECT_UI_FORBIDDEN
        if use_machine_scope:
            self._flags |= CRYPTPROTECT_LOCAL_MACHINE
        self._entropy = entropy
        self._is_windows = sys.platform == "win32"
        self._setup_win32_functions()

    @property
    def provider_name(self) -> str:
        return "windows_dpapi"

    @property
    def is_available(self) -> bool:
        if not self._is_windows:
            return False
        return hasattr(self, "_CryptProtectData") and self._CryptProtectData is not None

    def _setup_win32_functions(self) -> None:
        """Bind Win32 crypt32 APIs if running on Windows."""
        if not self._is_windows:
            logger.warning("Windows DPAPI is only supported natively on Windows NT.")
            return

        try:
            self._crypt32 = ctypes.windll.crypt32
            self._kernel32 = ctypes.windll.kernel32

            self._CryptProtectData = self._crypt32.CryptProtectData
            self._CryptProtectData.argtypes = [
                ctypes.POINTER(DATA_BLOB),
                wintypes.LPCWSTR,
                ctypes.POINTER(DATA_BLOB),
                ctypes.c_void_p,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(DATA_BLOB),
            ]
            self._CryptProtectData.restype = wintypes.BOOL

            self._CryptUnprotectData = self._crypt32.CryptUnprotectData
            self._CryptUnprotectData.argtypes = [
                ctypes.POINTER(DATA_BLOB),
                ctypes.POINTER(wintypes.LPWSTR),
                ctypes.POINTER(DATA_BLOB),
                ctypes.c_void_p,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.POINTER(DATA_BLOB),
            ]
            self._CryptUnprotectData.restype = wintypes.BOOL
        except Exception as e:
            logger.error("Failed to load Win32 crypt32.dll for DPAPI: %s", e)

    def protect(self, plaintext_bytes: bytes) -> bytes:
        """Encrypt plaintext bytes with Windows DPAPI."""
        if not self._is_windows:
            raise DPAPIError("Windows DPAPI is not available on non-Windows platforms.")

        if not plaintext_bytes:
            return b""

        # Prepare input blob
        in_buf = (ctypes.c_byte * len(plaintext_bytes))(*plaintext_bytes)
        in_blob = DATA_BLOB(len(plaintext_bytes), in_buf)

        # Prepare entropy blob
        p_entropy = None
        if self._entropy:
            ent_buf = (ctypes.c_byte * len(self._entropy))(*self._entropy)
            ent_blob = DATA_BLOB(len(self._entropy), ent_buf)
            p_entropy = ctypes.byref(ent_blob)

        out_blob = DATA_BLOB()

        success = self._CryptProtectData(
            ctypes.byref(in_blob),
            "BUDDY_DPAPI_PROTECTED",
            p_entropy,
            None,
            None,
            self._flags,
            ctypes.byref(out_blob),
        )

        if not success:
            err = ctypes.GetLastError()
            raise DPAPIError(f"CryptProtectData failed with Windows error code: {err}")

        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            self._kernel32.LocalFree(out_blob.pbData)

    def unprotect(self, ciphertext_bytes: bytes) -> bytes:
        """Decrypt DPAPI-protected ciphertext bytes."""
        if not self._is_windows:
            raise DPAPIError("Windows DPAPI is not available on non-Windows platforms.")

        if not ciphertext_bytes:
            return b""

        # Prepare input blob
        in_buf = (ctypes.c_byte * len(ciphertext_bytes))(*ciphertext_bytes)
        in_blob = DATA_BLOB(len(ciphertext_bytes), in_buf)

        # Prepare entropy blob
        p_entropy = None
        if self._entropy:
            ent_buf = (ctypes.c_byte * len(self._entropy))(*self._entropy)
            ent_blob = DATA_BLOB(len(self._entropy), ent_buf)
            p_entropy = ctypes.byref(ent_blob)

        out_blob = DATA_BLOB()

        success = self._CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            p_entropy,
            None,
            None,
            self._flags,
            ctypes.byref(out_blob),
        )

        if not success:
            err = ctypes.GetLastError()
            raise DPAPIError(f"CryptUnprotectData failed with Windows error code: {err}")

        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            self._kernel32.LocalFree(out_blob.pbData)

    def _get_secret_path(self, identifier: str) -> Path:
        """Sanitize identifier and map to file path."""
        safe_id = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in identifier)
        return self._vault_dir / f"{safe_id}.dpapi"

    def store(
        self,
        identifier: str,
        secret_value: str,
        metadata: Optional[Dict[str, Any]] = None,
        sensitivity: SecretSensitivity = SecretSensitivity.HIGHLY_SENSITIVE,
    ) -> SecretMetadata:
        """Encrypt and persist secret."""
        if not identifier:
            raise SecretStorageError("Secret identifier cannot be empty.")

        try:
            # 1. Encrypt secret with DPAPI
            raw_bytes = secret_value.encode("utf-8")
            encrypted = self.protect(raw_bytes)
            encoded_payload = base64.b64encode(encrypted).decode("ascii")

            # 2. Check existing version
            version = 1
            meta_path = self._get_secret_path(identifier)
            if meta_path.exists():
                try:
                    old_data = json.loads(meta_path.read_text(encoding="utf-8"))
                    version = old_data.get("metadata", {}).get("version", 0) + 1
                except Exception:
                    version = 2

            # 3. Create metadata
            now = time.time()
            sec_meta = SecretMetadata(
                identifier=identifier,
                provider=self.provider_name,
                created_at=now if version == 1 else old_data.get("metadata", {}).get("created_at", now),
                updated_at=now,
                rotation_required=False,
                sensitivity=sensitivity or SecretSensitivity.HIGHLY_SENSITIVE,
                version=version,
                description=(metadata or {}).get("description"),
            )

            # 4. Atomic write
            payload = {
                "metadata": sec_meta.model_dump(),
                "ciphertext": encoded_payload,
            }
            tmp_path = meta_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp_path.replace(meta_path)

            logger.info("Secret '%s' stored securely using Windows DPAPI (version=%d)", identifier, version)
            return sec_meta

        except Exception as e:
            raise SecretStorageError(f"Failed to store secret '{identifier}' in DPAPI: {e}") from e

    def retrieve(self, identifier: str) -> str:
        """Retrieve and decrypt secret with DPAPI."""
        meta_path = self._get_secret_path(identifier)
        if not meta_path.exists():
            raise SecretNotFoundError(identifier)

        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            ciphertext_b64 = data.get("ciphertext")
            if not ciphertext_b64:
                raise DPAPIError("Corrupted DPAPI secret payload: ciphertext missing.")

            raw_cipher = base64.b64decode(ciphertext_b64)
            decrypted = self.unprotect(raw_cipher)
            return decrypted.decode("utf-8")
        except SecretNotFoundError:
            raise
        except Exception as e:
            raise DPAPIError(f"Failed to retrieve or unprotect secret '{identifier}': {e}") from e

    def delete(self, identifier: str) -> bool:
        """Delete secret file."""
        meta_path = self._get_secret_path(identifier)
        if meta_path.exists():
            meta_path.unlink()
            logger.info("Deleted secret '%s' from DPAPI vault", identifier)
            return True
        return False

    def exists(self, identifier: str) -> bool:
        return self._get_secret_path(identifier).exists()

    def list_metadata(self) -> List[SecretMetadata]:
        results: List[SecretMetadata] = []
        for file in self._vault_dir.glob("*.dpapi"):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                meta = data.get("metadata")
                if meta:
                    results.append(SecretMetadata(**meta))
            except Exception as e:
                logger.warning("Could not read secret metadata from '%s': %s", file.name, e)
        return results

    def rotate(self, identifier: str, new_secret_value: str) -> SecretRotationResult:
        """Rotate secret preserving old value on failure."""
        if not self.exists(identifier):
            raise SecretNotFoundError(identifier)

        old_secret = self.retrieve(identifier)
        old_meta = next((m for m in self.list_metadata() if m.identifier == identifier), None)
        old_version = old_meta.version if old_meta else 1

        try:
            new_meta = self.store(identifier, new_secret_value)
            # Verify retrieval of new secret immediately
            retrieved = self.retrieve(identifier)
            if retrieved != new_secret_value:
                raise SecretStorageError("Verification mismatch during rotation.")

            return SecretRotationResult(
                identifier=identifier,
                success=True,
                old_version=old_version,
                new_version=new_meta.version,
                message="Secret rotated successfully via Windows DPAPI",
            )
        except Exception as e:
            # Revert to old secret
            self.store(identifier, old_secret)
            raise DPAPIError(f"Rotation of secret '{identifier}' failed (reverted to previous): {e}") from e

    def health(self) -> HealthCheckResult:
        """Diagnostic round-trip check using DPAPI."""
        if not self._is_windows:
            return HealthCheckResult(
                name="provider.windows_dpapi",
                status=HealthStatus.DEGRADED,
                message="Windows DPAPI unavailable on non-Windows host",
                timestamp=time.time(),
            )

        start = time.perf_counter()
        test_payload = b"buddy_health_probe"
        try:
            cipher = self.protect(test_payload)
            plain = self.unprotect(cipher)
            if plain != test_payload:
                raise DPAPIError("Health probe decrypted mismatch.")

            return HealthCheckResult(
                name="provider.windows_dpapi",
                status=HealthStatus.HEALTHY,
                message="Windows DPAPI cryptographic provider operational",
                timestamp=time.time(),
                latency=time.perf_counter() - start,
                details={"scope": "CurrentUser", "flags": self._flags},
            )
        except Exception as e:
            return HealthCheckResult(
                name="provider.windows_dpapi",
                status=HealthStatus.UNHEALTHY,
                message=f"Windows DPAPI probe failed: {e}",
                timestamp=time.time(),
                latency=time.perf_counter() - start,
            )
