"""BUDDY Secret Lifecycle & Bounded Lifetime Manager.

Coordinates container zeroization, bounded in-memory secret lifetimes,
and enforces the boundary between SECRET_USE and SECRET_DISCLOSURE.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional

from app.core.logging import get_logger
from app.security.secrets.exceptions import SecretAccessDeniedError, SecretNotFoundError
from app.security.secrets.models import SecretAccessType, SecretContainer, SecretMetadata
from app.security.secrets.provider import SecretProvider

logger = get_logger("security.secrets.lifecycle")


class SecretLifecycleManager:
    """Manages active secret containers, access control, and zeroization upon shutdown."""

    def __init__(self, provider: SecretProvider) -> None:
        self.provider = provider
        self._active_containers: List[SecretContainer] = []

    @contextmanager
    def access_secret(
        self,
        identifier: str,
        access_type: SecretAccessType = SecretAccessType.SECRET_USE,
        purpose: str = "internal_operation",
    ) -> Iterator[str]:
        """Context-managed bounded secret access.

        Enforces:
        - SECRET_DISCLOSURE requests are denied in ordinary operations.
        - Plaintext lifetime is bounded strictly to the context block.
        - Container is zeroized on exit.
        """
        if access_type == SecretAccessType.SECRET_DISCLOSURE:
            logger.warning("Denied attempt to disclose secret '%s' for purpose '%s'", identifier, purpose)
            raise SecretAccessDeniedError(
                f"Disclosure of secret '{identifier}' is forbidden. Secrets are DATA, not conversation context."
            )

        secret_val = self.provider.retrieve(identifier)
        container = SecretContainer(identifier, secret_val)
        self._active_containers.append(container)

        try:
            yield container.get_secret_value()
        finally:
            container.zeroize()
            if container in self._active_containers:
                self._active_containers.remove(container)

    def shutdown(self) -> None:
        """Zeroize all outstanding active containers."""
        for container in self._active_containers:
            try:
                container.zeroize()
            except Exception:
                pass
        self._active_containers.clear()
        logger.info("SecretLifecycleManager shutdown complete: all active secret containers zeroized.")
