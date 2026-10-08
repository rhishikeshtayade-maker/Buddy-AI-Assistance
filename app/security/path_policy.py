"""BUDDY Centralized Path Security Policy.

Guards filesystem operations against path traversal, symlink escapes, UNC exploits,
Windows reserved device names, and access to protected system or credential stores.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Set, Union

from app.core.exceptions import PathSecurityError

logger = logging.getLogger("buddy.security.path")

# Windows reserved device names that cannot be read/written
WINDOWS_DEVICE_NAMES: Set[str] = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}

# Forbidden directories and system locations
FORBIDDEN_SYSTEM_PATHS: Set[str] = {
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\recovery",
    "c:\\system volume information",
    "c:\\boot",
    "/etc",
    "/bin",
    "/sbin",
    "/usr",
    "/var",
    "/sys",
    "/proc",
    "/dev",
}

# Protected user/credential directories and patterns
PROTECTED_PATTERNS: Set[str] = {
    ".ssh",
    ".gnupg",
    ".aws",
    ".azure",
    ".kube",
    ".git",
    ".password-store",
    "credentials",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "id_dsa",
    "known_hosts",
    "authorized_keys",
    "ntuser.dat",
    "sam",
    "system",
    "security",
}


class PathPolicy:
    """Enforces strict filesystem sandboxing and path traversal defenses."""

    def __init__(
        self,
        allowed_roots: Optional[Iterable[Union[str, Path]]] = None,
        allow_cwd: bool = False,
    ) -> None:
        """Initialize PathPolicy.

        If allowed_roots is None, defaults to user Documents, Downloads, and Desktop.
        """
        self._allowed_roots: List[Path] = []

        if allowed_roots is not None:
            for r in allowed_roots:
                resolved = Path(r).resolve()
                self._allowed_roots.append(resolved)
        else:
            try:
                home = Path.home().resolve()
            except RuntimeError:
                userprofile = os.environ.get("USERPROFILE") or os.environ.get("HOME")
                home = Path(userprofile).resolve() if userprofile else Path.cwd().resolve()
            default_roots = [
                home / "Documents",
                home / "Downloads",
                home / "Desktop",
            ]
            for root in default_roots:
                self._allowed_roots.append(root.resolve())

        if allow_cwd:
            self._allowed_roots.append(Path.cwd().resolve())

    @property
    def allowed_roots(self) -> List[Path]:
        return list(self._allowed_roots)

    def add_allowed_root(self, root: Union[str, Path]) -> None:
        """Add an allowed directory root."""
        resolved = Path(root).resolve()
        if resolved not in self._allowed_roots:
            self._allowed_roots.append(resolved)

    def validate_path(self, raw_path: Union[str, Path], write: bool = False) -> Path:
        """Validate and resolve a path against sandboxing and security rules.

        Returns:
            Canonical resolved Path object.

        Raises:
            PathSecurityError: If the path violates any security policy.
        """
        str_path = str(raw_path).strip()
        if not str_path:
            raise PathSecurityError("Path cannot be empty.")

        # 1. Reject UNC and Windows Device Namespace paths
        if str_path.startswith(("\\\\", "//", "\\\\?\\", "\\\\.\\", "//?/", "//./")):
            raise PathSecurityError(f"UNC and raw device paths are strictly forbidden: '{str_path}'")

        # 2. Check for explicit path traversal patterns in raw string
        # While resolve() normalizes .., detecting it before or checking component names prevents tricks
        normalized_str = str_path.replace("/", "\\")
        parts = [p.strip() for p in normalized_str.split("\\") if p.strip()]

        for part in parts:
            stem = part.split(".")[0].upper()
            if stem in WINDOWS_DEVICE_NAMES:
                raise PathSecurityError(f"Windows reserved device name forbidden: '{part}'")

        # 3. Canonical resolution (resolves symlinks, junctions, and relative dots)
        try:
            path_obj = Path(str_path)
            # If path does not exist, resolve its parent to handle symlinks safely
            resolved = path_obj.resolve()
        except Exception as e:
            raise PathSecurityError(f"Path resolution failure for '{str_path}': {e}") from e

        resolved_str = str(resolved).lower()

        # 4. Check forbidden system roots
        for forbidden in FORBIDDEN_SYSTEM_PATHS:
            if resolved_str == forbidden or resolved_str.startswith(forbidden + "\\") or resolved_str.startswith(forbidden + "/"):
                raise PathSecurityError(f"Access to protected system path is forbidden: '{resolved}'")

        # 5. Check protected file and folder patterns (.ssh, .env, credentials, etc.)
        for part in resolved.parts:
            lower_part = part.lower()
            if lower_part in PROTECTED_PATTERNS:
                raise PathSecurityError(f"Access to protected security path '{part}' is forbidden.")
            if lower_part.startswith(".env"):
                raise PathSecurityError(f"Access to environment secret file '{part}' is forbidden.")
            if lower_part.endswith((".pem", ".key", ".pfx", ".p12")):
                raise PathSecurityError(f"Access to cryptographic key/cert file '{part}' is forbidden.")

        # Also check file name specifically
        file_name_lower = resolved.name.lower()
        if file_name_lower.startswith(".env") or file_name_lower in PROTECTED_PATTERNS:
            raise PathSecurityError(f"Access to protected file '{resolved.name}' is forbidden.")

        # 6. Verify path resides strictly within one of the allowed roots
        is_inside_root = False
        for root in self._allowed_roots:
            try:
                # relative_to will succeed if resolved is equal to or a child of root
                resolved.relative_to(root)
                is_inside_root = True
                break
            except ValueError:
                # On Windows, path comparison can be case-insensitive
                if os.name == "nt":
                    try:
                        resolved_lower = Path(str(resolved).lower())
                        root_lower = Path(str(root).lower())
                        resolved_lower.relative_to(root_lower)
                        is_inside_root = True
                        break
                    except ValueError:
                        continue
                continue

        if not is_inside_root:
            raise PathSecurityError(
                f"Path '{resolved}' is outside allowed sandboxed roots: {[str(r) for r in self._allowed_roots]}"
            )

        return resolved

    def is_path_allowed(self, raw_path: Union[str, Path], write: bool = False) -> bool:
        """Check if path is allowed without throwing exceptions."""
        try:
            self.validate_path(raw_path, write=write)
            return True
        except PathSecurityError:
            return False
