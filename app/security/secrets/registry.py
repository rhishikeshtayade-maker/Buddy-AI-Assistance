"""BUDDY Secret Provider Registry.

Manages available secret providers (Windows DPAPI, Credential Manager, Mock)
and coordinates default provider resolution.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from app.core.logging import get_logger
from app.security.secrets.provider import SecretProvider

logger = get_logger("security.secrets.registry")


class SecretProviderRegistry:
    """Registry maintaining available secret storage provider backends."""

    def __init__(self) -> None:
        self._providers: Dict[str, SecretProvider] = {}
        self._default_provider_name: Optional[str] = None

    def register(self, provider: SecretProvider, is_default: bool = False) -> None:
        """Register a provider instance."""
        name = provider.provider_name
        self._providers[name] = provider
        if is_default or self._default_provider_name is None:
            self._default_provider_name = name
        logger.debug("Registered secret provider: %s (default=%s)", name, is_default)

    def get(self, name: Optional[str] = None) -> Optional[SecretProvider]:
        """Retrieve provider by name, or return default."""
        if name:
            return self._providers.get(name)
        if self._default_provider_name:
            return self._providers.get(self._default_provider_name)
        return next(iter(self._providers.values()), None)

    def list_providers(self) -> List[str]:
        return list(self._providers.keys())
