"""BUDDY AI Provider & Conversational Brain Subsystem.

Provides AI provider abstractions (Cloud, Local, Mock), provider router,
conversation manager, system prompts, message models, and typed conversation events.
"""

from app.ai.conversation import ConversationManager
from app.ai.events import (
    AIRequestStartedEvent,
    AIResponseReceivedEvent,
    ConversationEndedEvent,
    ConversationErrorEvent,
    ConversationStartedEvent,
    UserMessageReceivedEvent,
)
from app.ai.exceptions import (
    AIAuthenticationError,
    AIError,
    AIModelError,
    AIProviderError,
    AIRateLimitError,
    AITimeoutError,
    ConversationError,
)
from app.ai.models import (
    AIResponse,
    ChatMessage,
    ContentSource,
    MessageRole,
)
from app.ai.prompts import (
    BUDDY_SYSTEM_PROMPT,
    is_untrusted_source,
    wrap_untrusted_content,
)
from app.ai.provider import (
    AIProvider,
    CloudAIProvider,
    LocalAIProvider,
    MockAIProvider,
)
from app.ai.router import AIRouter

__all__ = [
    # Models & Enums
    "MessageRole",
    "ContentSource",
    "ChatMessage",
    "AIResponse",
    # Events
    "ConversationStartedEvent",
    "UserMessageReceivedEvent",
    "AIRequestStartedEvent",
    "AIResponseReceivedEvent",
    "ConversationErrorEvent",
    "ConversationEndedEvent",
    # Exceptions
    "AIError",
    "AIProviderError",
    "AIAuthenticationError",
    "AIRateLimitError",
    "AITimeoutError",
    "AIModelError",
    "ConversationError",
    # Prompts
    "BUDDY_SYSTEM_PROMPT",
    "wrap_untrusted_content",
    "is_untrusted_source",
    # Providers & Router
    "AIProvider",
    "MockAIProvider",
    "CloudAIProvider",
    "LocalAIProvider",
    "AIRouter",
    # Conversation Manager
    "ConversationManager",
]
