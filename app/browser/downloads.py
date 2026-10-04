"""BUDDY Controlled Browser Downloads.

Enforces download directory containment, filename sanitization,
dangerous extension restrictions, and size quota validation.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional, Set

from app.browser.config import BrowserConfig
from app.browser.exceptions import BrowserDownloadError

logger = logging.getLogger("buddy.browser.downloads")

# Dangerous executable file extensions requiring strict restriction
DANGEROUS_EXTENSIONS: Set[str] = {
    ".exe",
    ".msi",
    ".bat",
    ".cmd",
    ".ps1",
    ".vbs",
    ".js",
    ".scr",
    ".com",
    ".pif",
    ".hta",
    ".vbe",
    ".wsf",
    ".jar",
    ".reg",
}


class DownloadManager:
    """Manages secure downloads from browser sessions."""

    def __init__(self, config: Optional[BrowserConfig] = None) -> None:
        self._config = config or BrowserConfig()
        self._download_dir = Path(self._config.browser_download_dir).resolve()
        self._download_dir.mkdir(parents=True, exist_ok=True)

    @property
    def download_dir(self) -> Path:
        return self._download_dir

    def sanitize_filename(self, filename: str) -> str:
        """Sanitize filename to prevent directory traversal and filesystem attacks."""
        if not filename:
            return "download.bin"

        # Strip directory traversal patterns
        clean = re.sub(r"\.\.+", "", filename.strip())
        clean = re.sub(r"[/\\]+", "_", clean).strip("_")
        base = os.path.basename(clean)
        # Remove invalid Windows filename characters: <>:"/\|?*
        base = re.sub(r'[<>:"/\\|?*]', "_", base).strip(" .")

        if not base:
            base = "download.bin"

        return base

    def validate_download_target(self, filename: str) -> Path:
        """Validate target destination path and enforce directory containment."""
        safe_name = self.sanitize_filename(filename)
        dest_path = (self._download_dir / safe_name).resolve()

        # Enforce containment inside download directory
        try:
            dest_path.relative_to(self._download_dir)
        except ValueError:
            raise BrowserDownloadError(
                f"Path traversal detected: destination '{dest_path}' escapes download directory."
            )

        # Check dangerous file extensions
        ext = dest_path.suffix.lower()
        if ext in DANGEROUS_EXTENSIONS:
            logger.warning("Download of potentially dangerous executable file '%s' requested", safe_name)
            # Dangerous extensions are restricted or flagged
            raise BrowserDownloadError(
                f"Download rejected: dangerous executable file extension '{ext}' is prohibited without explicit elevated approval."
            )

        return dest_path

    def validate_file_size(self, file_path: Path) -> int:
        """Verify that downloaded file does not exceed maximum configured quota."""
        if not file_path.exists():
            raise BrowserDownloadError(f"Downloaded file '{file_path}' does not exist.")

        size_bytes = file_path.stat().st_size
        limit_mb = min(self._config.browser_max_download_size_mb, self._config.max_browser_download_size_mb)
        max_bytes = limit_mb * 1024 * 1024

        if size_bytes > max_bytes:
            # Remove oversized file to protect disk space
            try:
                file_path.unlink()
            except Exception:
                pass
            raise BrowserDownloadError(
                f"Downloaded file exceeded maximum allowed size of {limit_mb} MB "
                f"({size_bytes} bytes > {max_bytes} bytes)."
            )

        return size_bytes
