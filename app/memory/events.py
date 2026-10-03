"""BUDDY Long-Term Memory Lifecycle Events.

Defines safe, privacy-preserving events for creation, retrieval, updates,
expiration, conflicts, and deletion of memories.
NEVER contains raw sensitive text, credentials, or private contents.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.core.events import BaseEvent
from app.memory.models import MemorySensitivity, MemorySource, MemoryType


@dataclass(frozen=True)
class MemoryCreatedEvent(BaseEvent):
    """Emitted when a memory record is validated and saved to store."""

    memory_id: str = ""
    memory_type: str = MemoryType.SEMANTIC.value
    source: str = MemorySource.USER_EXPLICIT.value
    sensitivity: str = MemorySensitivity.PERSONAL.value


@dataclass(frozen=True)
class MemoryUpdatedEvent(BaseEvent):
    """Emitted when an existing memory is updated or has its access timestamp refreshed."""

    memory_id: str = ""
    memory_type: str = MemoryType.SEMANTIC.value
    version: int = 1


@dataclass(frozen=True)
class MemoryDeletedEvent(BaseEvent):
    """Emitted when a memory is explicitly deleted or forgotten."""

    memory_id: str = ""
    memory_type: str = MemoryType.SEMANTIC.value
    reason: str = "user_command"


@dataclass(frozen=True)
class MemoryExpiredEvent(BaseEvent):
    """Emitted when a time-bound session or episodic memory exceeds its TTL."""

    memory_id: str = ""
    memory_type: str = MemoryType.SESSION.value


@dataclass(frozen=True)
class MemoryRetrievedEvent(BaseEvent):
    """Emitted when memories are queried and selected for context injection."""

    query_length: int = 0
    records_retrieved: int = 0


@dataclass(frozen=True)
class MemoryConfirmedEvent(BaseEvent):
    """Emitted when a user confirms promotion of an AI-inferred memory to permanent status."""

    memory_id: str = ""


@dataclass(frozen=True)
class MemoryRejectedEvent(BaseEvent):
    """Emitted when a proposed memory candidate is rejected by policy or secret detection."""

    reason: str = ""
    source: str = MemorySource.AI_INFERRED.value


@dataclass(frozen=True)
class MemoryConflictDetectedEvent(BaseEvent):
    """Emitted when a new memory contradicts an existing memory."""

    existing_memory_id: str = ""
    new_memory_id: Optional[str] = None
    resolution: str = "prefer_newer_explicit"


@dataclass(frozen=True)
class MemoryClearedEvent(BaseEvent):
    """Emitted when a category or all memories are wiped."""

    memory_type: Optional[str] = None
    records_cleared: int = 0
