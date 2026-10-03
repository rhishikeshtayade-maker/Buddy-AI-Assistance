"""BUDDY AI Provider & Conversational Brain Exception Hierarchy.

Defines typed exceptions for AI generation failures, router errors,
authentication issues, rate limits, timeouts, and conversation context errors.
"""

from typing import Optional
from app.core.exceptions import BuddyError


class AIError(BuddyError):
    """Base exception for all AI subsystem failures."""


class AIProviderError(AIError):
    """Raised when an AI provider fails during inference or connectivity."""

    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[dict] = None,
    ) -> None:
        d = details or {}
        if provider:
            d["provider"] = provider
        if model:
            d["model"] = model
        if status_code is not None:
            d["status_code"] = status_code
        super().__init__(message, details=d)
        self.provider = provider
        self.model = model
        self.status_code = status_code


class AIAuthenticationError(AIProviderError):
    """Raised when an AI provider rejects authentication or API key."""


class AIRateLimitError(AIProviderError):
    """Raised when an AI provider enforces rate limiting or quota exhaustion."""

    def __init__(
        self,
        message: str,
        retry_after: Optional[float] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> None:
        d = details or {}
        if retry_after is not None:
            d["retry_after"] = retry_after
        super().__init__(message, provider=provider, model=model, status_code=429, details=d)
        self.retry_after = retry_after


class AITimeoutError(AIProviderError):
    """Raised when an AI generation request exceeds configured timeout."""


class AIModelError(AIProviderError):
    """Raised when the requested AI model is unavailable or returned a malformed response."""


class ConversationError(AIError):
    """Raised when conversation context or state management encounters an error."""
