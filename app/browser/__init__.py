"""BUDDY Browser Automation Subsystem (Loop 9).

Provides secure, policy-enforced browser automation using Playwright.
All external web content is treated as untrusted data.
"""

from __future__ import annotations

from app.browser.models import (
    BrowserAction,
    BrowserActionResult,
    BrowserActionType,
    BrowserEngine,
    BrowserRiskLevel,
    BrowserSessionStatus,
    BrowserTabStatus,
    BrowserTarget,
    FormField,
    FormFieldSensitivity,
)
from app.browser.exceptions import (
    BrowserError,
    BrowserSecurityError,
    BrowserNavigationError,
    BrowserSessionError,
    BrowserTabError,
    BrowserTargetError,
    BrowserVerificationError,
    BrowserDownloadError,
    BrowserUploadError,
    BrowserPromptInjectionError,
    BrowserTimeoutError,
)
from app.browser.policy import BrowserPolicy
from app.browser.service import BrowserService

__all__ = [
    "BrowserAction",
    "BrowserActionResult",
    "BrowserActionType",
    "BrowserEngine",
    "BrowserRiskLevel",
    "BrowserSessionStatus",
    "BrowserTabStatus",
    "BrowserTarget",
    "FormField",
    "FormFieldSensitivity",
    "BrowserError",
    "BrowserSecurityError",
    "BrowserNavigationError",
    "BrowserSessionError",
    "BrowserTabError",
    "BrowserTargetError",
    "BrowserVerificationError",
    "BrowserDownloadError",
    "BrowserUploadError",
    "BrowserPromptInjectionError",
    "BrowserTimeoutError",
    "BrowserPolicy",
    "BrowserService",
]
