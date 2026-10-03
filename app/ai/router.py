"""BUDDY AI Router.

Selects and dispatches requests to the appropriate AI Provider based on
system configuration and runtime options.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.ai.exceptions import AIProviderError
from app.ai.provider import (
    AIProvider,
    CloudAIProvider,
    LocalAIProvider,
    MockAIProvider,
)
from app.core.config import BuddyConfig

logger = logging.getLogger("buddy.ai.router")


class AIRouter:
    """Manages AI provider selection, registration, and fallback routing."""

    def __init__(self, config: Optional[BuddyConfig] = None) -> None:
        self._config = config or BuddyConfig.load_from_env()
        self._providers: Dict[str, AIProvider] = {}
        self._setup_default_providers()

    def _setup_default_providers(self) -> None:
        """Register default provider instances based on configuration."""
        # 1. Mock Provider (Always available for tests and offline fallbacks)
        mock_provider = MockAIProvider(model=self._config.ai_model)
        self.register_provider("mock", mock_provider)

        # 2. Cloud Provider (OpenAI-compatible)
        cloud_provider = CloudAIProvider(
            api_key=self._config.ai_api_key,
            base_url=self._config.ai_base_url or "https://api.openai.com/v1",
            model=self._config.ai_model,
            timeout=self._config.ai_timeout,
            max_retries=self._config.ai_max_retries,
        )
        self.register_provider("cloud", cloud_provider)
        self.register_provider("openai", cloud_provider)

        # 3. Local Provider (Ollama / Local LLM)
        local_provider = LocalAIProvider(
            base_url="http://localhost:11434",
            model=self._config.ai_model,
            timeout=self._config.ai_timeout,
        )
        self.register_provider("local", local_provider)
        self.register_provider("ollama", local_provider)

    def register_provider(self, name: str, provider: AIProvider) -> None:
        """Register an AI provider under a lookup key."""
        key = name.strip().lower()
        self._providers[key] = provider

    def get_provider(self, name: Optional[str] = None) -> AIProvider:
        """Resolve the active AI provider.

        Uses explicit name if provided, otherwise defaults to config.ai_provider.
        Raises AIProviderError if requested provider is unknown.
        """
        target = (name or self._config.ai_provider).strip().lower()

        if target not in self._providers:
            available = sorted(self._providers.keys())
            raise AIProviderError(
                f"Unknown AI provider '{target}'. Available providers: {available}",
                provider=target,
            )

        return self._providers[target]

    def list_providers(self) -> List[str]:
        """Return list of registered provider names."""
        return sorted(self._providers.keys())
