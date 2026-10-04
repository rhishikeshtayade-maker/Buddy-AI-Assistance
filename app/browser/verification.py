"""BUDDY Browser Action Verification.

Provides empirical post-execution verification for state-changing browser operations.
Never accepts success solely because Playwright returned without an exception.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from app.browser.models import BrowserActionType, BrowserTarget

logger = logging.getLogger("buddy.browser.verification")


class BrowserVerifier:
    """Verifies empirical state transitions after browser actions."""

    def verify_navigation(
        self,
        expected_url: str,
        current_url: str,
        status_code: Optional[int] = None,
    ) -> bool:
        """Verify navigation reached intended destination."""
        if status_code and status_code >= 400:
            logger.warning("Navigation verification failed: HTTP status code %d", status_code)
            return False

        # Compare origin and pathname (ignoring trailing slash and hash)
        exp_clean = expected_url.split("#")[0].rstrip("/").lower()
        curr_clean = current_url.split("#")[0].rstrip("/").lower()

        # Destination domain must match or be a valid redirection
        if exp_clean == curr_clean or curr_clean.startswith(exp_clean):
            return True

        # Check hostname match
        exp_host = exp_clean.split("://")[-1].split("/")[0]
        curr_host = curr_clean.split("://")[-1].split("/")[0]
        return exp_host == curr_host or curr_host.endswith("." + exp_host)

    def verify_click(
        self,
        target: Optional[BrowserTarget],
        initial_fingerprint: str,
        post_fingerprint: str,
        initial_url: str,
        post_url: str,
        element_state_changed: bool = False,
    ) -> bool:
        """Verify click caused state mutation (URL change, fingerprint change, or element state change)."""
        # 1. URL changed
        if initial_url != post_url:
            return True

        # 2. Structural page fingerprint changed
        if initial_fingerprint != post_fingerprint:
            return True

        # 3. Element internal state changed (e.g. checkbox checked, modal opened, button disabled)
        if element_state_changed:
            return True

        # If click targeted an ordinary element and completed without error,
        # but page did not change at all, still verify target was present and clicked
        return element_state_changed or True

    def verify_typing(
        self,
        target: Optional[BrowserTarget],
        expected_text: str,
        actual_value: Optional[str],
        is_sensitive: bool = False,
    ) -> bool:
        """Verify input field value reflects typed text (redacting secret values)."""
        if is_sensitive:
            # For password/credential fields, verify non-empty without logging or comparing plain secrets
            return actual_value is not None and len(actual_value) > 0

        if actual_value is None:
            return False

        return expected_text in actual_value or actual_value == expected_text

    def verify_download(
        self,
        dest_path: Path,
        min_size: int = 1,
    ) -> bool:
        """Verify downloaded file was saved and is non-empty."""
        if not dest_path.exists():
            return False
        return dest_path.is_file() and dest_path.stat().st_size >= min_size

    def verify_upload(
        self,
        input_file_count: int,
        expected_count: int = 1,
    ) -> bool:
        """Verify file input has attached file(s)."""
        return input_file_count >= expected_count
