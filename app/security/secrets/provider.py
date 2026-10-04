"""BUDDY Secret Provider Interface.

Abstract base contract for native Windows DPAPI, Windows Credential Manager,
and testing secret vaults. Enforces fail-closed operation and disclosure guards.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.core.health import HealthCheckResult
from app.security.secrets.models import SecretMetadata, SecretRotationResult


class SecretProvider(ABC):
    """Abstract interface for secure secret backends."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Identifying name of this provider (e.g. 'windows_dpapi')."""
        ...

    @property
    def is_available(self) -> bool:
        """Indicates whether this provider backend is functional on the current system."""
        return True

    @abstractmethod
    def store(
        self,
        identifier: str,
        secret_value: str,
        metadata: Optional[Dict[str, Any]] = None,
        sensitivity: Any = None,
    ) -> SecretMetadata:
        """Store or overwrite a secret securely."""
        ...

    @abstractmethod
    def retrieve(self, identifier: str) -> str:
        """Retrieve a secret by identifier. Raises SecretNotFoundError if missing."""
        ...

    @abstractmethod
    def delete(self, identifier: str) -> bool:
        """Remove a secret from storage. Returns True if deleted, False if not found."""
        ...

    @abstractmethod
    def exists(self, identifier: str) -> bool:
        """Check if a secret identifier exists in this provider."""
        ...

    @abstractmethod
    def list_metadata(self) -> List[SecretMetadata]:
        """List metadata for all managed secrets without revealing values."""
        ...

    @abstractmethod
    def rotate(self, identifier: str, new_secret_value: str) -> SecretRotationResult:
        """Atomically rotate a secret value, retaining known-good version on failure."""
        ...

    @abstractmethod
    def health(self) -> HealthCheckResult:
        """Return diagnostic health check for HealthManager."""
        ...

    def __repr__(self) -> str:
        return f"<SecretProvider provider='{self.provider_name}'>"

    def __str__(self) -> str:
        return self.__repr__()
