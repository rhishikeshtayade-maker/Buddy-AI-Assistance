"""BUDDY Browser Exceptions.

Strongly typed exception hierarchy for browser automation, security violations,
SSRF detection, stale target errors, prompt injection detection, and timeouts.
"""

from __future__ import annotations

from app.core.exceptions import BuddyError, SecurityError


class BrowserError(BuddyError):
    """Base exception for all browser subsystem errors."""
    pass


class BrowserSecurityError(SecurityError, BrowserError):
    """Raised when a browser action violates security policy (SSRF, malicious scheme, blocked domain)."""
    pass


class BrowserNavigationError(BrowserError):
    """Raised when navigation fails or times out."""
    pass


class BrowserSessionError(BrowserError):
    """Raised when session creation, management, or lifecycle encounters an error."""
    pass


class BrowserTabError(BrowserError):
    """Raised when tab management (switch, close, lookup) fails."""
    pass


class BrowserTargetError(BrowserError):
    """Raised when element target identification or lookup fails."""
    pass


class StaleTargetError(BrowserTargetError):
    """Raised when an element target is stale or its page fingerprint has changed."""
    pass


class AmbiguousTargetError(BrowserTargetError):
    """Raised when an element selector or identifier matches multiple ambiguous targets."""
    pass


class LowConfidenceTargetError(BrowserTargetError):
    """Raised when element target confidence is below the required threshold."""
    pass


class BrowserVerificationError(BrowserError):
    """Raised when empirical verification after a browser action fails."""
    pass


class BrowserDownloadError(BrowserError):
    """Raised when download validation, size limit, or path policy fails."""
    pass


class BrowserUploadError(BrowserError):
    """Raised when upload validation, size limit, or path policy fails."""
    pass


class BrowserPromptInjectionError(BrowserSecurityError):
    """Raised when webpage content contains adversarial prompt injection attempting to override system directives."""
    pass


class BrowserTimeoutError(BrowserError):
    """Raised when a browser action or wait operation exceeds its timeout."""
    pass
