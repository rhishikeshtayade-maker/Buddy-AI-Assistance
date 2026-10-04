"""BUDDY Browser Models.

Strongly typed Pydantic models for browser automation, session management,
targets, actions, results, and sensitive form classification.
All models strictly enforce extra='forbid'.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum, IntEnum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class BrowserEngine(str, Enum):
    """Supported browser engines."""
    CHROMIUM = "chromium"
    EDGE = "edge"


class BrowserSessionStatus(str, Enum):
    """Lifecycle states of a browser session."""
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    CLOSING = "closing"
    CLOSED = "closed"
    ERROR = "error"


class BrowserTabStatus(str, Enum):
    """Status of an open browser tab."""
    ACTIVE = "active"
    BACKGROUND = "background"
    CLOSED = "closed"


class BrowserActionType(str, Enum):
    """Permitted browser automation action types."""
    NAVIGATE = "navigate"
    BACK = "back"
    FORWARD = "forward"
    RELOAD = "reload"
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    TYPE = "type"
    PRESS_KEY = "press_key"
    SELECT = "select"
    SCROLL = "scroll"
    EXTRACT_TEXT = "extract_text"
    SCREENSHOT = "screenshot"
    DOWNLOAD = "download"
    UPLOAD = "upload"
    WAIT = "wait"
    FOCUS = "focus"


class BrowserRiskLevel(IntEnum):
    """Deterministic risk classification for browser actions."""
    SAFE = 0
    LOW = 1
    MODERATE = 2
    HIGH = 3
    CRITICAL = 4


class FormFieldSensitivity(str, Enum):
    """Classification of form fields for sensitive data protection."""
    SAFE = "safe"
    PERSONAL = "personal"
    SENSITIVE = "sensitive"
    CREDENTIAL = "credential"
    PAYMENT = "payment"


class FormField(BaseModel):
    """Metadata describing a form input element and its sensitivity."""
    field_id: str = Field(..., description="Unique element identifier or selector")
    name: Optional[str] = Field(default=None, description="Input name attribute")
    field_type: str = Field(default="text", description="Input type (text, password, email, etc.)")
    label: Optional[str] = Field(default=None, description="Associated label text")
    sensitivity: FormFieldSensitivity = Field(default=FormFieldSensitivity.SAFE, description="Field sensitivity rating")
    required: bool = Field(default=False, description="Whether field is required")
    placeholder: Optional[str] = Field(default=None, description="Input placeholder text")

    model_config = {
        "extra": "forbid",
    }


class BrowserTarget(BaseModel):
    """Layered identification for a target browser element."""
    target_id: str = Field(..., description="Unique target identifier within active page")
    selector: Optional[str] = Field(default=None, description="CSS selector or Playwright locator")
    role: Optional[str] = Field(default=None, description="Accessibility role (button, link, textbox, etc.)")
    accessible_name: Optional[str] = Field(default=None, description="Accessibility name/label")
    text: Optional[str] = Field(default=None, description="Visible text content")
    bounding_box: Optional[Dict[str, float]] = Field(default=None, description="Bounding box {x, y, width, height}")
    page_url: str = Field(..., description="URL of the page where target was discovered")
    page_fingerprint: str = Field(..., description="Structural fingerprint of the page at discovery")
    confidence: float = Field(default=0.85, ge=0.0, le=1.0, description="Target identification confidence")
    target_type: str = Field(default="element", description="Target classification (element, input, button, link)")

    model_config = {
        "extra": "forbid",
    }

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if v < 0.0 or v > 1.0:
            raise ValueError(f"Confidence must be between 0.0 and 1.0, got {v}")
        return v


class BrowserAction(BaseModel):
    """Structured, policy-governed browser action request."""
    action_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action_type: BrowserActionType = Field(..., description="Type of browser operation")
    target: Optional[BrowserTarget] = Field(default=None, description="Target element if applicable")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Action-specific arguments")
    page_fingerprint: Optional[str] = Field(default=None, description="Expected page fingerprint for stale validation")
    session_id: str = Field(..., description="Target browser session identifier")
    tab_id: Optional[str] = Field(default=None, description="Target tab identifier (defaults to active tab)")
    risk_level: BrowserRiskLevel = Field(default=BrowserRiskLevel.SAFE, description="Assigned risk tier")
    requested_at: float = Field(default_factory=time.time, description="Unix timestamp of request")

    model_config = {
        "extra": "forbid",
    }


class BrowserActionResult(BaseModel):
    """Structured result of a verified browser action execution."""
    action_id: str = Field(..., description="Matching action ID")
    success: bool = Field(default=False, description="True ONLY if action executed and verified")
    status: str = Field(default="completed", description="Execution outcome status")
    result: Any = Field(default=None, description="Safe result data")
    verification: bool = Field(default=False, description="True ONLY if post-action verification passed")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional non-sensitive metadata")

    model_config = {
        "extra": "forbid",
    }


class BrowserPageInfo(BaseModel):
    """Safe, bounded snapshot of current browser tab state."""
    session_id: str
    tab_id: str
    url: str
    title: str
    page_fingerprint: str
    is_sensitive: bool = False
    has_captcha: bool = False
    has_login: bool = False
    status_code: Optional[int] = None
    tabs_count: int = 1

    model_config = {
        "extra": "forbid",
    }
