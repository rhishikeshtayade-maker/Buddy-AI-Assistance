"""BUDDY Contextual Awareness Configuration.

Provides strongly typed configuration schema, validation rules,
and safe serialization for context observers and proactive assistance.
"""

from __future__ import annotations

import re
from typing import Any, Dict
from pydantic import BaseModel, Field, field_validator


class ContextAwarenessConfig(BaseModel):
    """Configuration options for contextual awareness and proactive assistance."""

    # Master switches
    context_awareness_enabled: bool = Field(
        default=True,
        description="Master switch for the entire contextual awareness subsystem",
    )
    foreground_observer_enabled: bool = Field(
        default=True,
        description="Monitor focused application identity and window title",
    )
    activity_observer_enabled: bool = Field(
        default=True,
        description="Monitor coarse activity states (ACTIVE/IDLE/AWAY)",
    )
    notification_observer_enabled: bool = Field(
        default=True,
        description="Observe OS notification events via untrusted provider",
    )
    calendar_enabled: bool = Field(
        default=True,
        description="Integrate calendar event deadlines via provider interface",
    )
    browser_context_enabled: bool = Field(
        default=True,
        description="Ingest permitted browser metadata (domain/category only)",
    )
    proactive_assistance_enabled: bool = Field(
        default=True,
        description="Allow BUDDY to generate suggestions and action proposals",
    )

    # Activity thresholds (seconds)
    activity_idle_threshold: float = Field(
        default=300.0,
        ge=10.0,
        le=7200.0,
        description="Inactivity duration in seconds before user is considered IDLE (default: 5 min)",
    )
    activity_away_threshold: float = Field(
        default=900.0,
        ge=30.0,
        le=86400.0,
        description="Inactivity duration in seconds before user is considered AWAY (default: 15 min)",
    )

    # Interruption & Quiet Hours
    quiet_hours_enabled: bool = Field(
        default=False,
        description="Enforce quiet hours where proactive interruptions are silenced",
    )
    quiet_hours_start: str = Field(
        default="22:00",
        description="Quiet hours start time in HH:MM (24-hour format)",
    )
    quiet_hours_end: str = Field(
        default="07:00",
        description="Quiet hours end time in HH:MM (24-hour format)",
    )

    # Interruption Budget & Cooldowns
    suggestion_cooldown_seconds: float = Field(
        default=600.0,
        ge=0.0,
        le=86400.0,
        description="Minimum seconds before an identical suggestion can be repeated (default: 10 min)",
    )
    max_interruptions_per_hour: int = Field(
        default=6,
        ge=1,
        le=60,
        description="Maximum proactive interruptions allowed per rolling hour window",
    )

    # Context Retention & Privacy
    context_history_enabled: bool = Field(
        default=False,
        description="Store ephemeral historical context snapshots (disabled by default)",
    )
    context_history_ttl: float = Field(
        default=3600.0,
        ge=60.0,
        le=86400.0,
        description="Time-to-live for ephemeral context snapshots in seconds",
    )
    sensitive_context_suppression_enabled: bool = Field(
        default=True,
        description="Automatically sanitize context and suppress suggestions in sensitive applications",
    )

    # Performance Polling
    observer_poll_interval_seconds: float = Field(
        default=2.0,
        ge=0.2,
        le=60.0,
        description="Polling cadence for foreground & activity observers",
    )
    calendar_poll_interval_seconds: float = Field(
        default=30.0,
        ge=5.0,
        le=600.0,
        description="Polling interval for upcoming calendar events",
    )

    @field_validator("quiet_hours_start", "quiet_hours_end")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        """Validate HH:MM format."""
        if not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", v):
            raise ValueError(f"Time '{v}' must be in 24-hour HH:MM format (e.g. '22:00')")
        return v

    def to_safe_dict(self) -> Dict[str, Any]:
        """Serialize configuration safely."""
        return self.model_dump()
