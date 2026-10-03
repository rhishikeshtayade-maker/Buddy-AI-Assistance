"""BUDDY Long-Term Memory Models & Strongly Typed Schema.

Defines memory categories (Session, Semantic, Episodic, Profile),
provenance sources, sensitivity levels, lifecycle statuses, and immutable records.
"""

from __future__ import annotations

from enum import Enum
import time
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, field_validator


class MemoryType(str, Enum):
    """Categorization of memory lifespan and role."""

    SESSION = "session"       # Temporary, active conversation/task context only
    SEMANTIC = "semantic"     # Cross-session facts, stable user preferences, project context
    EPISODIC = "episodic"     # Summarized past interactions and completed task outcomes
    PROFILE = "profile"       # Explicitly user-approved personal identifiers and directives


class MemorySource(str, Enum):
    """Provenance and authority tier of a memory entry."""

    USER_EXPLICIT = "user_explicit"       # Highest authority: User directly commanded memory
    USER_CONFIRMED = "user_confirmed"     # Candidate presented to user and confirmed
    AI_INFERRED = "ai_inferred"           # Extracted by AI reasoning; provisional, lower trust
    SYSTEM_GENERATED = "system_generated" # System runtime/task summary
    IMPORTED = "imported"                 # Imported from external user-approved profile


class MemorySensitivity(str, Enum):
    """Security classification of stored content."""

    PUBLIC = "public"         # General non-sensitive facts
    PERSONAL = "personal"     # User preferences, favorite editor, workflows
    SENSITIVE = "sensitive"   # Protected private data (requires encryption if enabled)
    SECRET = "secret"         # Passwords, API keys, tokens — MUST NEVER BE STORED


class MemoryStatus(str, Enum):
    """Lifecycle status of a memory record."""

    ACTIVE = "active"
    EXPIRED = "expired"
    ARCHIVED = "archived"
    DELETED = "deleted"


class MemoryRecord(BaseModel):
    """Strongly typed, validated unit of stored memory."""

    memory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    memory_type: MemoryType = Field(default=MemoryType.SEMANTIC)
    source: MemorySource = Field(default=MemorySource.USER_EXPLICIT)
    sensitivity: MemorySensitivity = Field(default=MemorySensitivity.PERSONAL)
    content: str = Field(..., min_length=1, description="Sanitized memory fact or preference")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    status: MemoryStatus = Field(default=MemoryStatus.ACTIVE)
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    last_accessed_at: float = Field(default_factory=time.time)
    expires_at: Optional[float] = None
    user_confirmed: bool = Field(default=False)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    version: int = Field(default=1, ge=1)

    model_config = {
        "extra": "forbid",
    }

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, v: str) -> str:
        cleaned = v.strip()
        if not cleaned:
            raise ValueError("Memory content cannot be empty or whitespace only.")
        return cleaned


class MemoryCandidate(BaseModel):
    """Provisional memory candidate proposed by AI or parser prior to policy evaluation."""

    content: str = Field(..., min_length=1)
    memory_type: MemoryType = Field(default=MemoryType.SEMANTIC)
    source: MemorySource = Field(default=MemorySource.AI_INFERRED)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "forbid"}


class MemoryCommandAction(str, Enum):
    """Natural language memory intent actions."""

    REMEMBER = "remember"
    FORGET = "forget"
    SHOW = "show"
    CLEAR_SESSION = "clear_session"
    CLEAR_ALL = "clear_all"


class MemoryCommand(BaseModel):
    """Parsed user memory command."""

    action: MemoryCommandAction
    target_content: Optional[str] = None
    memory_type: Optional[MemoryType] = None
    confirmation_required: bool = False

    model_config = {"extra": "forbid"}
