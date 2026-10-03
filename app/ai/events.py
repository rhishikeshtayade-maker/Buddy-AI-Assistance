"""BUDDY Conversational AI Events.

Defines typed events for conversation lifecycle, prompt dispatch,
AI model responses, and conversation error monitoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.core.events import BaseEvent


@dataclass(frozen=True)
class ConversationStartedEvent(BaseEvent):
    """Emitted when a new conversation session begins."""

    session_id: str = "default"
    provider: str = "mock"
    model: str = "mock-v1"


@dataclass(frozen=True)
class UserMessageReceivedEvent(BaseEvent):
    """Emitted when user input is ingested into the conversation."""

    session_id: str = "default"
    content_length: int = 0
    source: str = "user_input"


@dataclass(frozen=True)
class AIRequestStartedEvent(BaseEvent):
    """Emitted immediately prior to dispatching messages to an AI provider."""

    session_id: str = "default"
    provider: str = "mock"
    model: str = "mock-v1"
    message_count: int = 0


@dataclass(frozen=True)
class AIResponseReceivedEvent(BaseEvent):
    """Emitted when a response is received from the AI provider."""

    session_id: str = "default"
    provider: str = "mock"
    model: str = "mock-v1"
    content: str = ""
    latency: float = 0.0
    finish_reason: Optional[str] = "stop"


@dataclass(frozen=True)
class ConversationErrorEvent(BaseEvent):
    """Emitted when an AI request or conversation cycle fails."""

    session_id: str = "default"
    error_type: str = "AIError"
    message: str = "An AI error occurred"
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ConversationEndedEvent(BaseEvent):
    """Emitted when a conversation session ends or is reset."""

    session_id: str = "default"
    total_turns: int = 0
