"""BUDDY Encryption Key Lifecycle Manager.

Manages cryptographically secure key generation, storage, retrieval,
and rotation for memory encryption, master keys, and provider secrets.
"""

from __future__ import annotations

import base64
import secrets
from typing import Optional

from app.core.logging import get_logger
from app.security.secrets.exceptions import SecretNotFoundError, SecretStorageError
from app.security.secrets.models import SecretRotationResult
from app.security.secrets.provider import SecretProvider

logger = get_logger("security.secrets.key_mgr")

BUDDY_MASTER_KEY = "BUDDY_MASTER_KEY"
BUDDY_MEMORY_ENCRYPTION_KEY = "BUDDY_MEMORY_ENCRYPTION_KEY"
BUDDY_OPENAI_API_KEY = "BUDDY_OPENAI_API_KEY"
BUDDY_BROWSER_CREDENTIAL = "BUDDY_BROWSER_CREDENTIAL"


class KeyManager:
    """Orchestrates encryption key generation, lifecycle, and provider storage."""

    def __init__(self, provider: SecretProvider) -> None:
        self.provider = provider

    def generate_random_key(self, length_bytes: int = 32) -> str:
        """Generate cryptographically secure URL-safe base64 key."""
        raw = secrets.token_bytes(length_bytes)
        return base64.urlsafe_b64encode(raw).decode("ascii")

    def get_key(self, identifier: str) -> str:
        """Retrieve key value. Fails closed with SecretNotFoundError if absent."""
        return self.provider.retrieve(identifier)

    def get_or_create_key(self, identifier: str, length_bytes: int = 32) -> str:
        """Retrieve existing key or generate and store a new secure key."""
        try:
            return self.get_key(identifier)
        except SecretNotFoundError:
            new_key = self.generate_random_key(length_bytes=length_bytes)
            self.provider.store(
                identifier=identifier,
                secret_value=new_key,
                metadata={"description": f"Auto-generated key for {identifier}"},
            )
            logger.info("Generated and stored new secure key for '%s'", identifier)
            return new_key

    def rotate_key(self, identifier: str, length_bytes: int = 32) -> SecretRotationResult:
        """Atomically rotate key with a freshly generated cryptographic secret."""
        new_key = self.generate_random_key(length_bytes=length_bytes)
        return self.provider.rotate(identifier, new_key)
