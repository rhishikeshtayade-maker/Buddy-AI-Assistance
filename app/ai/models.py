"""BUDDY Conversational AI Data Models.

Defines message structures, role definitions, untrusted content categorization,
and structured AI response models.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class MessageRole(str, Enum):
    """Roles participating in a conversational AI exchange."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    EXTERNAL = "external"


class ContentSource(str, Enum):
    """Categorization of message provenance for security and prompt injection defenses."""

    INTERNAL = "internal"                     # Direct system instructions or core logic
    USER_INPUT = "user_input"                 # Direct prompt entered by authenticated user
    UNTRUSTED_EXTERNAL = "untrusted_external" # Text scraped from websites, emails, or docs
    TOOL_RESULT = "tool_result"               # Verified output from local tool execution


@dataclass(frozen=True)
class ChatMessage:
    """Strongly typed message unit within a conversation history."""

    role: MessageRole
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    source: ContentSource = ContentSource.USER_INPUT

    def to_dict(self) -> Dict[str, Any]:
        """Convert to standard provider-compatible dictionary representation."""
        # Provider wire protocols usually require 'role' and 'content'
        return {
            "role": self.role.value,
            "content": self.content,
        }


@dataclass(frozen=True)
class AIResponse:
    """Structured response produced by an AI Provider."""

    content: str
    finish_reason: Optional[str] = "stop"
    provider: str = "mock"
    model: str = "mock-v1"
    usage: Optional[Dict[str, int]] = None
    latency: float = 0.0
    tool_calls: Optional[List[Dict[str, Any]]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
