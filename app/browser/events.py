"""BUDDY Browser Automation Events.

Defines safe, typed events emitted across the browser subsystem lifecycle.
NEVER contains credentials, raw secrets, or untrusted payload injections.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.events import BaseEvent


@dataclass(frozen=True)
class BrowserSessionCreatedEvent(BaseEvent):
    session_id: str = ""
    engine: str = "chromium"
    headless: bool = True


@dataclass(frozen=True)
class BrowserSessionStartedEvent(BaseEvent):
    session_id: str = ""
    browser_version: str = ""


@dataclass(frozen=True)
class BrowserSessionClosedEvent(BaseEvent):
    session_id: str = ""
    reason: str = "normal"


@dataclass(frozen=True)
class BrowserTabCreatedEvent(BaseEvent):
    session_id: str = ""
    tab_id: str = ""


@dataclass(frozen=True)
class BrowserTabClosedEvent(BaseEvent):
    session_id: str = ""
    tab_id: str = ""


@dataclass(frozen=True)
class BrowserNavigationStartedEvent(BaseEvent):
    session_id: str = ""
    tab_id: str = ""
    url: str = ""


@dataclass(frozen=True)
class BrowserNavigationCompletedEvent(BaseEvent):
    session_id: str = ""
    tab_id: str = ""
    url: str = ""
    status_code: Optional[int] = None
    title: str = ""
    fingerprint: str = ""


@dataclass(frozen=True)
class BrowserActionRequestedEvent(BaseEvent):
    action_id: str = ""
    session_id: str = ""
    action_type: str = ""
    target_id: Optional[str] = None
    risk_level: str = "SAFE"


@dataclass(frozen=True)
class BrowserActionConfirmedEvent(BaseEvent):
    action_id: str = ""
    session_id: str = ""
    action_type: str = ""


@dataclass(frozen=True)
class BrowserActionRejectedEvent(BaseEvent):
    action_id: str = ""
    session_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class BrowserActionExecutedEvent(BaseEvent):
    action_id: str = ""
    session_id: str = ""
    action_type: str = ""
    latency: float = 0.0


@dataclass(frozen=True)
class BrowserActionVerifiedEvent(BaseEvent):
    action_id: str = ""
    session_id: str = ""
    action_type: str = ""
    verified: bool = False


@dataclass(frozen=True)
class BrowserDownloadStartedEvent(BaseEvent):
    session_id: str = ""
    url: str = ""
    suggested_filename: str = ""


@dataclass(frozen=True)
class BrowserDownloadCompletedEvent(BaseEvent):
    session_id: str = ""
    filename: str = ""
    file_size_bytes: int = 0
    mime_type: Optional[str] = None


@dataclass(frozen=True)
class BrowserUploadRequestedEvent(BaseEvent):
    session_id: str = ""
    filepath: str = ""
    file_size_bytes: int = 0


@dataclass(frozen=True)
class BrowserUploadCompletedEvent(BaseEvent):
    session_id: str = ""
    filename: str = ""
    target_id: str = ""


@dataclass(frozen=True)
class BrowserPromptInjectionDetectedEvent(BaseEvent):
    session_id: str = ""
    url: str = ""
    pattern: str = ""
    snippet: str = ""


@dataclass(frozen=True)
class BrowserCaptchaDetectedEvent(BaseEvent):
    session_id: str = ""
    url: str = ""
    captcha_type: str = "unknown"


@dataclass(frozen=True)
class BrowserSensitiveFieldDetectedEvent(BaseEvent):
    session_id: str = ""
    field_id: str = ""
    field_type: str = "password"
    sensitivity: str = "credential"


@dataclass(frozen=True)
class BrowserTaskPausedEvent(BaseEvent):
    session_id: str = ""
    reason: str = "human_interaction_required"
