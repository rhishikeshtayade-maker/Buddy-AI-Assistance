"""BUDDY Controlled Browser Uploads.

Enforces PathPolicy sandboxing, credential exfiltration protection,
dangerous file type restrictions, and upload size quotas.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Set, Union

from app.browser.config import BrowserConfig
from app.browser.exceptions import BrowserUploadError
from app.core.exceptions import PathSecurityError
from app.security.path_policy import PathPolicy

logger = logging.getLogger("buddy.browser.uploads")

# Prohibited file extensions for uploads to external websites
BLOCKED_UPLOAD_EXTENSIONS: Set[str] = {
    ".exe",
    ".dll",
    ".sys",
    ".bat",
    ".cmd",
    ".ps1",
    ".vbs",
    ".key",
    ".pem",
    ".pfx",
    ".p12",
    ".kdbx",
    ".db",
    ".sqlite",
    ".sqlite3",
}

# Sensitive document extensions requiring elevated review
SENSITIVE_UPLOAD_EXTENSIONS: Set[str] = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".csv",
}


class UploadManager:
    """Validates and enforces security boundaries on files selected for browser upload."""

    def __init__(
        self,
        config: Optional[BrowserConfig] = None,
        path_policy: Optional[PathPolicy] = None,
    ) -> None:
        self._config = config or BrowserConfig()
        self._path_policy = path_policy or PathPolicy()

    def validate_upload_file(self, raw_path: Union[str, Path]) -> Path:
        """Validate local file before allowing it to be attached to a browser input.

        Raises:
            BrowserUploadError: If file violates path sandboxing, size, or credential protection.
        """
        if not raw_path:
            raise BrowserUploadError("Upload file path must not be empty.")

        # 1. Enforce core filesystem PathPolicy (prevents path traversal, .ssh, .env, SAM, credentials)
        try:
            resolved_path = self._path_policy.validate_path(raw_path, write=False)
        except PathSecurityError as e:
            raise BrowserUploadError(f"Upload rejected by PathPolicy: {e}") from e

        if not resolved_path.exists():
            raise BrowserUploadError(f"Upload file '{resolved_path}' does not exist.")

        if not resolved_path.is_file():
            raise BrowserUploadError(f"Upload path '{resolved_path}' is not a regular file.")

        # 2. Check blocked file extensions
        ext = resolved_path.suffix.lower()
        if ext in BLOCKED_UPLOAD_EXTENSIONS:
            raise BrowserUploadError(
                f"Upload rejected: prohibited executable or credential file extension '{ext}'."
            )

        # 3. Check for obvious credential file names
        stem_lower = resolved_path.stem.lower()
        if any(sec in stem_lower for sec in ("password", "credential", "secret", "private_key", "token")):
            raise BrowserUploadError(
                f"Upload rejected: sensitive file name '{resolved_path.name}' matches credential pattern."
            )

        # 4. Enforce upload size limit
        file_size = resolved_path.stat().st_size
        limit_mb = min(self._config.browser_max_upload_size_mb, self._config.max_browser_upload_size_mb)
        max_bytes = limit_mb * 1024 * 1024
        if file_size > max_bytes:
            raise BrowserUploadError(
                f"Upload file size exceeds maximum limit of {limit_mb} MB "
                f"({file_size} bytes > {max_bytes} bytes)."
            )

        return resolved_path

    def is_sensitive_upload(self, file_path: Path) -> bool:
        """Check if an upload file type warrants elevated user confirmation."""
        return file_path.suffix.lower() in SENSITIVE_UPLOAD_EXTENSIONS
