"""BUDDY Windows Credential Manager Provider.

Integrates with Windows Credential Manager (advapi32.dll) to store,
retrieve, rotate, and delete generic OS-managed credentials.
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from typing import Any, Dict, List, Optional

from app.core.health import HealthCheckResult, HealthStatus
from app.core.logging import get_logger
from app.security.secrets.exceptions import CredentialManagerError, SecretNotFoundError
from app.security.secrets.models import SecretMetadata, SecretRotationResult, SecretSensitivity
from app.security.secrets.provider import SecretProvider

logger = get_logger("security.secrets.cred_mgr")

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
TARGET_PREFIX = "BUDDY:"


class FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


PCREDENTIALW = ctypes.POINTER(CREDENTIALW)


class WindowsCredentialManagerProvider(SecretProvider):
    """Secure credential vault backed by native Windows Credential Manager."""

    def __init__(self, target_prefix: str = TARGET_PREFIX) -> None:
        self._target_prefix = target_prefix
        self._is_windows = sys.platform == "win32"
        self._setup_win32_functions()

    @property
    def provider_name(self) -> str:
        return "windows_credential_manager"

    @property
    def is_available(self) -> bool:
        if not self._is_windows:
            return False
        return hasattr(self, "_CredWriteW") and self._CredWriteW is not None

    def _setup_win32_functions(self) -> None:
        """Bind advapi32 Credential Manager APIs on Windows."""
        if not self._is_windows:
            return

        try:
            self._advapi32 = ctypes.windll.advapi32

            # CredWriteW
            self._CredWriteW = self._advapi32.CredWriteW
            self._CredWriteW.argtypes = [PCREDENTIALW, wintypes.DWORD]
            self._CredWriteW.restype = wintypes.BOOL

            # CredReadW
            self._CredReadW = self._advapi32.CredReadW
            self._CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(PCREDENTIALW)]
            self._CredReadW.restype = wintypes.BOOL

            # CredDeleteW
            self._CredDeleteW = self._advapi32.CredDeleteW
            self._CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
            self._CredDeleteW.restype = wintypes.BOOL

            # CredFree
            self._CredFree = self._advapi32.CredFree
            self._CredFree.argtypes = [ctypes.c_void_p]
            self._CredFree.restype = None

        except Exception as e:
            logger.error("Failed to bind Windows advapi32.dll credential functions: %s", e)

    def _format_target(self, identifier: str) -> str:
        if identifier.startswith(self._target_prefix):
            return identifier
        return f"{self._target_prefix}{identifier}"

    def _unformat_target(self, target: str) -> str:
        if target.startswith(self._target_prefix):
            return target[len(self._target_prefix):]
        return target

    def store(
        self,
        identifier: str,
        secret_value: str,
        metadata: Optional[Dict[str, Any]] = None,
        sensitivity: SecretSensitivity = SecretSensitivity.HIGHLY_SENSITIVE,
    ) -> SecretMetadata:
        """Store secret in Windows Credential Manager."""
        if not self._is_windows:
            raise CredentialManagerError("Windows Credential Manager is only supported on Windows.")

        target = self._format_target(identifier)
        val_bytes = secret_value.encode("utf-16-le")

        blob_buf = (ctypes.c_byte * len(val_bytes))(*val_bytes)

        cred = CREDENTIALW()
        cred.Flags = 0
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = target
        cred.Comment = "Managed by BUDDY Security Vault"
        cred.CredentialBlobSize = len(val_bytes)
        cred.CredentialBlob = ctypes.cast(blob_buf, ctypes.POINTER(ctypes.c_byte))
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        cred.UserName = "BUDDY_USER"

        success = self._CredWriteW(ctypes.byref(cred), 0)
        if not success:
            err = ctypes.GetLastError()
            raise CredentialManagerError(f"CredWriteW failed for '{target}' with error code {err}")

        logger.info("Secret '%s' stored in Windows Credential Manager", identifier)
        return SecretMetadata(
            identifier=identifier,
            provider=self.provider_name,
            created_at=time.time(),
            updated_at=time.time(),
            sensitivity=sensitivity or SecretSensitivity.HIGHLY_SENSITIVE,
            description=(metadata or {}).get("description"),
        )

    def retrieve(self, identifier: str) -> str:
        """Retrieve secret from Windows Credential Manager."""
        if not self._is_windows:
            raise CredentialManagerError("Windows Credential Manager is only supported on Windows.")

        target = self._format_target(identifier)
        p_cred = PCREDENTIALW()

        success = self._CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(p_cred))
        if not success:
            err = ctypes.GetLastError()
            # 1168 = ERROR_NOT_FOUND
            if err == 1168:
                raise SecretNotFoundError(identifier)
            raise CredentialManagerError(f"CredReadW failed for '{target}' with error code {err}")

        try:
            cred_obj = p_cred.contents
            blob_size = cred_obj.CredentialBlobSize
            raw_bytes = ctypes.string_at(cred_obj.CredentialBlob, blob_size)
            return raw_bytes.decode("utf-16-le")
        finally:
            self._CredFree(p_cred)

    def delete(self, identifier: str) -> bool:
        """Delete secret from Windows Credential Manager."""
        if not self._is_windows:
            return False

        target = self._format_target(identifier)
        success = self._CredDeleteW(target, CRED_TYPE_GENERIC, 0)
        if success:
            logger.info("Deleted secret '%s' from Windows Credential Manager", identifier)
            return True
        return False

    def exists(self, identifier: str) -> bool:
        """Check if secret exists in Windows Credential Manager."""
        try:
            self.retrieve(identifier)
            return True
        except SecretNotFoundError:
            return False
        except Exception:
            return False

    def list_metadata(self) -> List[SecretMetadata]:
        """List metadata for registered BUDDY credentials."""
        # For security and simplicity, returns empty or known list; CredEnumerate can be called
        # but generic enumeration requires special filter strings.
        return []

    def rotate(self, identifier: str, new_secret_value: str) -> SecretRotationResult:
        """Rotate secret in Windows Credential Manager."""
        old_val = self.retrieve(identifier)
        try:
            self.store(identifier, new_secret_value)
            # Verify retrieval
            val = self.retrieve(identifier)
            if val != new_secret_value:
                raise CredentialManagerError("Verification mismatch during Credential Manager rotation.")

            return SecretRotationResult(
                identifier=identifier,
                success=True,
                old_version=1,
                new_version=2,
                message="Credential rotated in Windows Credential Manager",
            )
        except Exception as e:
            self.store(identifier, old_val)
            raise CredentialManagerError(f"Rotation failed in Credential Manager (restored old): {e}") from e

    def health(self) -> HealthCheckResult:
        """Diagnostic probe for Windows Credential Manager."""
        if not self._is_windows:
            return HealthCheckResult(
                name="provider.windows_cred_mgr",
                status=HealthStatus.DEGRADED,
                message="Windows Credential Manager is unavailable on non-Windows host",
                timestamp=time.time(),
            )

        probe_id = "BUDDY_HEALTH_PROBE"
        test_val = "probe_test_val_123"
        start = time.perf_counter()
        try:
            self.store(probe_id, test_val)
            ret = self.retrieve(probe_id)
            self.delete(probe_id)
            if ret != test_val:
                raise CredentialManagerError("Health probe value mismatch.")

            return HealthCheckResult(
                name="provider.windows_cred_mgr",
                status=HealthStatus.HEALTHY,
                message="Windows Credential Manager operational",
                timestamp=time.time(),
                latency=time.perf_counter() - start,
            )
        except Exception as e:
            return HealthCheckResult(
                name="provider.windows_cred_mgr",
                status=HealthStatus.DEGRADED,
                message=f"Windows Credential Manager probe failed: {e}",
                timestamp=time.time(),
                latency=time.perf_counter() - start,
            )
