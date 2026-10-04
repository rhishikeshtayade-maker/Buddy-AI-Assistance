"""BUDDY Secure Secrets & Credential Vault Exceptions.

Typed exception hierarchy for Windows DPAPI, Credential Manager,
key management, secret rotation, migration, and access boundaries.
"""

from __future__ import annotations

from app.core.exceptions import BuddyError


class SecretError(BuddyError):
    """Base exception for all credential vault and secret management operations."""


class SecretNotFoundError(SecretError):
    """Raised when a requested secret identifier is not found in the vault."""

    def __init__(self, identifier: str) -> None:
        self.identifier = identifier
        super().__init__(f"Secret '{identifier}' was not found in the secure vault.")


class SecretStorageError(SecretError):
    """Raised when storing or persisting a secret fails."""


class SecretRetrievalError(SecretError):
    """Raised when retrieving or decrypting a secret fails."""


class SecretRotationError(SecretError):
    """Raised when secret rotation fails, ensuring known-good credentials remain intact."""


class SecretAccessDeniedError(SecretError):
    """Raised when an unauthorized disclosure or forbidden operation is attempted."""


class DPAPIError(SecretError):
    """Raised when Windows DPAPI encryption or decryption operations fail."""


class CredentialManagerError(SecretError):
    """Raised when Windows Credential Manager encounters an error."""


class SecretMigrationError(SecretError):
    """Raised when migrating legacy environment credentials into native vault fails."""


class SecretRedactionError(SecretError):
    """Raised when an error occurs during secret scanning or redaction."""


class VaultUnavailableError(SecretError):
    """Raised when no secure vault provider is available or operational."""


class KeyLifecycleError(SecretError):
    """Raised when cryptographic key generation or lifecycle operations fail."""
