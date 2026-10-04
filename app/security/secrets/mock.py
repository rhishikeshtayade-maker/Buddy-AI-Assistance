"""BUDDY Mock Secret Provider for Testing and CI.

Provides an isolated, in-memory implementation of SecretProvider
for unit testing and cross-platform simulation.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.core.health import HealthCheckResult, HealthStatus
from app.security.secrets.exceptions import SecretNotFoundError, SecretStorageError
from app.security.secrets.models import SecretMetadata, SecretRotationResult, SecretSensitivity
from app.security.secrets.provider import SecretProvider


class MockSecretProvider(SecretProvider):
    """In-memory deterministic secret provider for testing."""

    def __init__(self) -> None:
        self._secrets: Dict[str, str] = {}
        self._metadata: Dict[str, SecretMetadata] = {}
        self._is_healthy: bool = True

    @property
    def provider_name(self) -> str:
        return "mock_vault"

    def set_healthy(self, healthy: bool) -> None:
        self._is_healthy = healthy

    def store(
        self,
        identifier: str,
        secret_value: str,
        metadata: Optional[Dict[str, Any]] = None,
        sensitivity: SecretSensitivity = SecretSensitivity.HIGHLY_SENSITIVE,
    ) -> SecretMetadata:
        if not self._is_healthy:
            raise SecretStorageError("Mock secret vault simulated failure.")

        now = time.time()
        old_meta = self._metadata.get(identifier)
        version = (old_meta.version + 1) if old_meta else 1

        sec_meta = SecretMetadata(
            identifier=identifier,
            provider=self.provider_name,
            created_at=old_meta.created_at if old_meta else now,
            updated_at=now,
            rotation_required=False,
            sensitivity=sensitivity or SecretSensitivity.HIGHLY_SENSITIVE,
            version=version,
            description=(metadata or {}).get("description"),
        )
        self._secrets[identifier] = secret_value
        self._metadata[identifier] = sec_meta
        return sec_meta

    def retrieve(self, identifier: str) -> str:
        if not self._is_healthy:
            raise RuntimeError("Mock secret vault is unhealthy.")

        if identifier not in self._secrets:
            raise SecretNotFoundError(identifier)
        return self._secrets[identifier]

    def delete(self, identifier: str) -> bool:
        if identifier in self._secrets:
            del self._secrets[identifier]
            self._metadata.pop(identifier, None)
            return True
        return False

    def exists(self, identifier: str) -> bool:
        return identifier in self._secrets

    def list_metadata(self) -> List[SecretMetadata]:
        return list(self._metadata.values())

    def rotate(self, identifier: str, new_secret_value: str) -> SecretRotationResult:
        if identifier not in self._secrets:
            raise SecretNotFoundError(identifier)

        old_meta = self._metadata[identifier]
        new_meta = self.store(identifier, new_secret_value)

        return SecretRotationResult(
            identifier=identifier,
            success=True,
            old_version=old_meta.version,
            new_version=new_meta.version,
            message="Secret rotated successfully in mock vault",
        )

    def health(self) -> HealthCheckResult:
        return HealthCheckResult(
            name="provider.secrets.mock",
            status=HealthStatus.HEALTHY if self._is_healthy else HealthStatus.UNHEALTHY,
            message="Mock secret provider operational" if self._is_healthy else "Mock secret provider simulated failure",
            timestamp=time.time(),
        )

    def clear(self) -> None:
        self._secrets.clear()
        self._metadata.clear()
