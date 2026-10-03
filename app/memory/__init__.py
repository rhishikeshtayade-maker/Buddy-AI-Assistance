"""BUDDY Long-Term Memory & Contextual Personalization Package.

Provides secure, bounded, privacy-conscious memory subsystem separating:
- Session Memory (temporary, active session only)
- Semantic Memory (stable cross-session user preferences)
- Episodic Memory (summarized past interaction outcomes)
- Profile Memory (explicit user directives and identity)

Subordinate to Security Policy, Tool Permissions, Confirmation, and Authentication.
Memory is contextual data, NEVER security authority.
"""

from __future__ import annotations

from app.memory.encryption import (
    FernetMemoryEncryptor,
    MemoryEncryptor,
    NoOpMemoryEncryptor,
    get_memory_encryptor,
)
from app.memory.events import (
    MemoryClearedEvent,
    MemoryConfirmedEvent,
    MemoryConflictDetectedEvent,
    MemoryCreatedEvent,
    MemoryDeletedEvent,
    MemoryExpiredEvent,
    MemoryRejectedEvent,
    MemoryRetrievedEvent,
    MemoryUpdatedEvent,
)
from app.memory.manager import MemoryManager
from app.memory.models import (
    MemoryCandidate,
    MemoryCommand,
    MemoryCommandAction,
    MemoryRecord,
    MemorySensitivity,
    MemorySource,
    MemoryStatus,
    MemoryType,
)
from app.memory.policy import MemoryPolicy, PolicyDecision, PolicyDecisionType
from app.memory.service import MemoryService
from app.memory.store import MemoryStore, SqliteMemoryStore

__all__ = [
    "MemoryType",
    "MemorySource",
    "MemorySensitivity",
    "MemoryStatus",
    "MemoryRecord",
    "MemoryCandidate",
    "MemoryCommand",
    "MemoryCommandAction",
    "MemoryStore",
    "SqliteMemoryStore",
    "MemoryPolicy",
    "PolicyDecision",
    "PolicyDecisionType",
    "MemoryEncryptor",
    "FernetMemoryEncryptor",
    "NoOpMemoryEncryptor",
    "get_memory_encryptor",
    "MemoryService",
    "MemoryManager",
    "MemoryCreatedEvent",
    "MemoryUpdatedEvent",
    "MemoryDeletedEvent",
    "MemoryExpiredEvent",
    "MemoryRetrievedEvent",
    "MemoryConfirmedEvent",
    "MemoryRejectedEvent",
    "MemoryConflictDetectedEvent",
    "MemoryClearedEvent",
]
