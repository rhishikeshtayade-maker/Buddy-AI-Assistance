"""BUDDY Secure Secrets and Credential Vault Subsystem.

Provides native Windows-backed DPAPI, Credential Manager, bounded secret lifetimes,
opaque identifier management, centralized redaction, and legacy memory key migration.
"""

from __future__ import annotations

from app.security.secrets.exceptions import (
    CredentialManagerError,
    DPAPIError,
    SecretAccessDeniedError,
    SecretError,
    SecretMigrationError,
    SecretNotFoundError,
    SecretRotationError,
    SecretStorageError,
    VaultUnavailableError,
)
from app.security.secrets.health import create_secret_vault_health_check
from app.security.secrets.key_manager import BUDDY_MEMORY_ENCRYPTION_KEY, KeyManager
from app.security.secrets.lifecycle import SecretLifecycleManager
from app.security.secrets.migration import KeyMigrator
from app.security.secrets.mock import MockSecretProvider
from app.security.secrets.models import (
    SecretAccessType,
    SecretContainer,
    SecretMetadata,
    SecretRotationResult,
    SecretSensitivity,
)
from app.security.secrets.provider import SecretProvider
from app.security.secrets.redaction import REDACTED_SECRET, redact_string, redact_structure
from app.security.secrets.registry import SecretProviderRegistry
from app.security.secrets.service import SecretVaultService
from app.security.secrets.windows_dpapi import WindowsDPAPIProvider

__all__ = [
    "BUDDY_MEMORY_ENCRYPTION_KEY",
    "CredentialManagerError",
    "DPAPIError",
    "KeyManager",
    "KeyMigrator",
    "MockSecretProvider",
    "REDACTED_SECRET",
    "SecretAccessDeniedError",
    "SecretAccessType",
    "SecretContainer",
    "SecretError",
    "SecretLifecycleManager",
    "SecretMetadata",
    "SecretMigrationError",
    "SecretNotFoundError",
    "SecretProvider",
    "SecretProviderRegistry",
    "SecretRotationError",
    "SecretRotationResult",
    "SecretSensitivity",
    "SecretStorageError",
    "SecretVaultService",
    "VaultUnavailableError",
    "WindowsDPAPIProvider",
    "create_secret_vault_health_check",
    "redact_string",
    "redact_structure",
]
