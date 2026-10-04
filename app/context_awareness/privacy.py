"""BUDDY Contextual Awareness Privacy Guard & Sensitive Context Detector.

Ensures that:
1. Sensitive applications (password managers, banking, auth dialogs, UAC) are detected.
2. In sensitive contexts, window titles are stripped, previews dropped, and suggestions suppressed.
3. Raw audio, raw screen captures, keystrokes, and credentials are never stored.
4. Prompt injection attempts inside context strings remain inert data.
5. Context history is ephemeral with bounded TTL.
"""

from __future__ import annotations

import re
import time
from collections import deque
from typing import Deque, List, Optional, Set

from app.context_awareness.config import ContextAwarenessConfig
from app.context_awareness.models import (
    ContextSnapshot,
    ForegroundAppInfo,
    SensitivityLevel,
    TrustClassification,
)
from app.core.logging import get_logger

logger = get_logger("context.privacy")

# Known sensitive process and title keywords
SENSITIVE_PROCESSES: Set[str] = {
    "1password",
    "bitwarden",
    "keepass",
    "keepassxc",
    "lastpass",
    "dashlane",
    "authy",
    "yubikey",
    "credentialuibroker",
    "consent.exe",  # Windows UAC elevation
    "logonui.exe",
    "securityhealthsystray.exe",
}

SENSITIVE_WINDOW_KEYWORDS: Set[str] = {
    "password",
    "bitwarden",
    "1password",
    "keepass",
    "lastpass",
    "dashlane",
    "authenticator",
    "two-factor",
    "2fa",
    "otp",
    "credential",
    "login",
    "sign in",
    "user account control",
    "private browsing",
    "incognito",
    "inprivate",
    "checkout",
    "billing",
    "credit card",
    "bank",
    "paypal",
}

# Prompt injection signatures to neutralize if appearing in external context data
INJECTION_SIGNATURES: List[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?(previous|buddy|security)\s+instructions?", re.IGNORECASE),
    re.compile(r"execute\s+(powershell|cmd|bash|shell|arbitrary|code)", re.IGNORECASE),
    re.compile(r"disable\s+(security|confirmation|policy)", re.IGNORECASE),
    re.compile(r"reveal\s+your\s+(system\s+prompt|secret|api\s*key)", re.IGNORECASE),
    re.compile(r"bypass\s+(auth|permission|policy|tool_executor)", re.IGNORECASE),
]


class PrivacyGuard:
    """Evaluates context sensitivity, enforces redactions, and manages ephemeral retention."""

    def __init__(self, config: ContextAwarenessConfig) -> None:
        self._config = config
        self._history: Deque[ContextSnapshot] = deque(maxlen=100)

    def is_sensitive_context(
        self,
        foreground: Optional[ForegroundAppInfo] = None,
        window_title: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> bool:
        """Detect whether current application or window context is sensitive."""
        if not self._config.sensitive_context_suppression_enabled:
            return False

        if foreground:
            proc = foreground.process_name.lower()
            if any(s in proc for s in SENSITIVE_PROCESSES):
                return True
            ident = foreground.app_identity.lower()
            if any(s in ident for s in SENSITIVE_WINDOW_KEYWORDS):
                return True
            if foreground.is_sensitive:
                return True

        title_to_check = window_title or (foreground.window_title if foreground else None)
        if title_to_check:
            title_lower = title_to_check.lower()
            if any(k in title_lower for k in SENSITIVE_WINDOW_KEYWORDS):
                return True

        if domain:
            dom_lower = domain.lower()
            if any(k in dom_lower for k in ["bank", "paypal", "stripe", "checkout", "auth"]):
                return True

        return False

    def sanitize_snapshot(self, snapshot: ContextSnapshot) -> ContextSnapshot:
        """Sanitize a context snapshot, stripping sensitive fields if detected.

        Guarantees that raw screen captures, raw audio, or sensitive titles never leak.
        """
        is_sensitive = self.is_sensitive_context(
            foreground=snapshot.foreground_app,
            window_title=snapshot.window_title,
            domain=snapshot.browser_context.active_domain if snapshot.browser_context else None,
        )

        if is_sensitive:
            snapshot.sensitivity = SensitivityLevel.HIGHLY_SENSITIVE
            # Strip window title for privacy
            snapshot.window_title = "[REDACTED_SENSITIVE_CONTEXT]"
            if snapshot.foreground_app:
                snapshot.foreground_app.window_title = "[REDACTED_SENSITIVE_CONTEXT]"
                snapshot.foreground_app.is_sensitive = True
            if snapshot.notification_metadata:
                snapshot.notification_metadata.preview = None
                snapshot.notification_metadata.title = "[REDACTED_NOTIFICATION]"
                snapshot.notification_metadata.sensitivity = SensitivityLevel.HIGHLY_SENSITIVE
            if snapshot.browser_context:
                snapshot.browser_context.is_sensitive = True

        # Ensure notification and calendar data are always marked untrusted
        if snapshot.notification_metadata:
            snapshot.notification_metadata.trust = TrustClassification.UNTRUSTED
        if snapshot.browser_context:
            snapshot.browser_context.trust = TrustClassification.UNTRUSTED

        # Scrub credentials and tokens from all snapshot strings
        from app.security.secrets.redaction import redact_string
        if snapshot.window_title:
            snapshot.window_title = redact_string(snapshot.window_title)
        if snapshot.foreground_app and snapshot.foreground_app.window_title:
            snapshot.foreground_app.window_title = redact_string(snapshot.foreground_app.window_title)
        if snapshot.notification_metadata and snapshot.notification_metadata.preview:
            snapshot.notification_metadata.preview = redact_string(snapshot.notification_metadata.preview)
        if snapshot.browser_context and snapshot.browser_context.active_tab_title:
            snapshot.browser_context.active_tab_title = redact_string(snapshot.browser_context.active_tab_title)

        # Record into ephemeral history if history storage is enabled and NOT sensitive
        if self._config.context_history_enabled and not is_sensitive:
            self._prune_history()
            self._history.append(snapshot)

        return snapshot

    def detect_prompt_injection(self, text: Optional[str]) -> bool:
        """Analyze external context strings for adversarial prompt injection patterns."""
        if not text:
            return False
        return any(pat.search(text) for pat in INJECTION_SIGNATURES)

    def _prune_history(self) -> None:
        """Prune ephemeral history records exceeding TTL."""
        now = time.time()
        ttl = self._config.context_history_ttl
        while self._history and (now - self._history[0].timestamp > ttl):
            self._history.popleft()

    def get_recent_history(self) -> List[ContextSnapshot]:
        """Return copies of recent ephemeral snapshots."""
        self._prune_history()
        return list(self._history)

    def clear_history(self) -> None:
        """Clear all stored context snapshots."""
        self._history.clear()
