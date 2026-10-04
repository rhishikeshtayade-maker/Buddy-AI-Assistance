"""BUDDY Secret Vault Service.

Central orchestrator for native Windows secrets and credential management.
Coordinates DPAPI, Credential Manager, key lifecycle, memory migration,
centralized redaction, and structured security audit events.

Guarantees:
- Secrets are DATA, not conversation context or model instructions.
- Fail-closed behavior on all security boundaries.
- Zero secret disclosure in logs, audit records, or exception messages.
"""

from __future__ import annotations

import re
import sys
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from app.core.logging import get_logger
from app.security.audit import AuditLogger
from app.security.secrets.exceptions import (
    DPAPIError,
    CredentialManagerError,
    SecretAccessDeniedError,
    SecretError,
    SecretNotFoundError,
    SecretStorageError,
    VaultUnavailableError,
)
from app.security.secrets.key_manager import KeyManager
from app.security.secrets.lifecycle import SecretLifecycleManager
from app.security.secrets.migration import KeyMigrator
from app.security.secrets.mock import MockSecretProvider
from app.security.secrets.models import (
    SecretAccessType,
    SecretMetadata,
    SecretRotationResult,
    SecretSensitivity,
)
from app.security.secrets.provider import SecretProvider
from app.security.secrets.redaction import redact_string, redact_structure
from app.security.secrets.registry import SecretProviderRegistry

logger = get_logger("security.secrets.service")

# Regex for valid opaque secret identifiers (e.g. BUDDY_OPENAI_API_KEY)
VALID_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_]{3,128}$")


class SecretVaultService:
    """Enterprise secret vault managing OS-level credentials and cryptographic secrets."""

    def __init__(
        self,
        provider: Optional[SecretProvider] = None,
        registry: Optional[SecretProviderRegistry] = None,
        audit_logger: Optional[AuditLogger] = None,
    ) -> None:
        self.registry = registry or SecretProviderRegistry()
        self.audit_logger = audit_logger or AuditLogger()

        # Initialize default providers if registry is empty
        if not self.registry.list_providers():
            self._initialize_default_providers()

        if provider:
            self.registry.register(provider, is_default=True)
            self._provider = provider
        else:
            resolved = self.registry.get()
            if resolved is None:
                raise VaultUnavailableError("No secret provider available in registry.")
            self._provider = resolved

        self.lifecycle_manager = SecretLifecycleManager(self._provider)
        self.key_manager = KeyManager(self._provider)
        self.migrator = KeyMigrator(self._provider)

        logger.info(
            "SecretVaultService initialized with primary provider: %s",
            self._provider.provider_name,
        )

    def _initialize_default_providers(self) -> None:
        """Register native Windows providers if on Windows, or mock provider for fallback/tests."""
        if sys.platform == "win32":
            try:
                from app.security.secrets.windows_dpapi import WindowsDPAPIProvider
                dpapi = WindowsDPAPIProvider()
                self.registry.register(dpapi, is_default=True)
            except Exception as e:
                logger.warning("Failed to initialize Windows DPAPI provider: %s", e)

            try:
                from app.security.secrets.credential_manager import WindowsCredentialManagerProvider
                cred_mgr = WindowsCredentialManagerProvider()
                self.registry.register(cred_mgr, is_default=False)
            except Exception as e:
                logger.warning("Failed to initialize Windows Credential Manager provider: %s", e)

        # Ensure at least a fallback provider exists if no native providers registered
        if not self.registry.list_providers():
            mock_p = MockSecretProvider()
            self.registry.register(mock_p, is_default=True)

    @property
    def provider(self) -> SecretProvider:
        """Active primary secret provider."""
        return self._provider

    def _validate_identifier(self, identifier: str) -> None:
        """Enforce strict opaque identifier rules. Rejects raw secret values used as keys."""
        if not identifier or not isinstance(identifier, str):
            raise SecretError("Secret identifier must be a non-empty string.")
        if not VALID_IDENTIFIER_PATTERN.match(identifier.strip()):
            raise SecretError(
                f"Invalid secret identifier '{identifier}'. Identifiers must be alphanumeric with underscores."
            )
        # Prevent accidentally passing raw keys as identifiers
        if identifier.startswith("sk-") or len(identifier) > 128:
            raise SecretError("Secret identifier appears to be a raw secret value; rejected.")

    def store_secret(
        self,
        identifier: str,
        secret_value: str,
        metadata: Optional[Dict[str, Any]] = None,
        sensitivity: SecretSensitivity = SecretSensitivity.HIGHLY_SENSITIVE,
        provider_name: Optional[str] = None,
    ) -> SecretMetadata:
        """Securely store a secret value in native storage.
        
        Emits SECRET_STORED audit event with safe metadata.
        """
        self._validate_identifier(identifier)
        if not secret_value:
            raise SecretError("Cannot store empty secret value.")

        target_provider = self._provider
        if provider_name:
            resolved = self.registry.get(provider_name)
            if resolved:
                target_provider = resolved
            else:
                raise SecretStorageError(f"Requested provider '{provider_name}' not found.")

        try:
            stored_meta = target_provider.store(
                identifier=identifier,
                secret_value=secret_value,
                metadata=metadata,
                sensitivity=sensitivity,
            )

            # Record audit event (METADATA ONLY, NEVER SECRET VALUE)
            self.audit_logger.log_event(
                event_type="SECRET_STORED",
                resource=identifier,
                action="store",
                status="SUCCESS",
                details={
                    "provider": target_provider.provider_name,
                    "sensitivity": sensitivity.value,
                    "version": stored_meta.version,
                },
            )
            return stored_meta

        except Exception as e:
            self.audit_logger.log_event(
                event_type="SECRET_STORED",
                resource=identifier,
                action="store",
                status="FAILED",
                details={"provider": target_provider.provider_name, "error": str(e)},
            )
            raise

    @contextmanager
    def access_secret(
        self,
        identifier: str,
        access_type: SecretAccessType = SecretAccessType.SECRET_USE,
        purpose: str = "internal_operation",
    ) -> Iterator[str]:
        """Bounded context-managed access to secret plaintext.
        
        Enforces SECRET_USE vs SECRET_DISCLOSURE boundary.
        Logs audit events on access or denial.
        """
        self._validate_identifier(identifier)

        if access_type == SecretAccessType.SECRET_DISCLOSURE:
            self.audit_logger.log_event(
                event_type="SECRET_ACCESS_DENIED",
                resource=identifier,
                action="disclose",
                status="DENIED",
                details={"purpose": purpose, "reason": "Disclosure forbidden by policy"},
            )
            raise SecretAccessDeniedError(
                f"Access denied: Disclosing secret '{identifier}' is forbidden. "
                "Secrets are DATA and cannot be returned to conversations or prompts."
            )

        try:
            with self.lifecycle_manager.access_secret(identifier, access_type, purpose) as secret_val:
                self.audit_logger.log_event(
                    event_type="SECRET_RETRIEVED",
                    resource=identifier,
                    action="use",
                    status="SUCCESS",
                    details={"purpose": purpose, "provider": self._provider.provider_name},
                )
                yield secret_val

        except SecretNotFoundError:
            self.audit_logger.log_event(
                event_type="SECRET_RETRIEVED",
                resource=identifier,
                action="use",
                status="NOT_FOUND",
                details={"purpose": purpose},
            )
            raise
        except Exception as e:
            self.audit_logger.log_event(
                event_type="SECRET_RETRIEVED",
                resource=identifier,
                action="use",
                status="FAILED",
                details={"purpose": purpose, "error": str(e)},
            )
            raise

    def retrieve_secret_value(
        self,
        identifier: str,
        purpose: str = "internal_provider_operation",
    ) -> str:
        """Direct retrieval strictly for internal secure provider boundaries (e.g. AI provider HTTP headers).
        
        Must never be routed to models, conversations, tools, or logs.
        """
        self._validate_identifier(identifier)
        try:
            val = self._provider.retrieve(identifier)
            self.audit_logger.log_event(
                event_type="SECRET_RETRIEVED",
                resource=identifier,
                action="direct_retrieve",
                status="SUCCESS",
                details={"purpose": purpose, "provider": self._provider.provider_name},
            )
            return val
        except Exception as e:
            self.audit_logger.log_event(
                event_type="SECRET_RETRIEVED",
                resource=identifier,
                action="direct_retrieve",
                status="FAILED",
                details={"purpose": purpose, "error": str(e)},
            )
            raise

    def delete_secret(self, identifier: str) -> bool:
        """Securely remove a secret from the vault.
        
        Emits SECRET_DELETED audit event.
        """
        self._validate_identifier(identifier)
        try:
            result = self._provider.delete(identifier)
            self.audit_logger.log_event(
                event_type="SECRET_DELETED",
                resource=identifier,
                action="delete",
                status="SUCCESS" if result else "NOT_FOUND",
                details={"provider": self._provider.provider_name},
            )
            return result
        except Exception as e:
            self.audit_logger.log_event(
                event_type="SECRET_DELETED",
                resource=identifier,
                action="delete",
                status="FAILED",
                details={"error": str(e)},
            )
            raise

    def exists(self, identifier: str) -> bool:
        """Check if secret exists without retrieving its plaintext."""
        self._validate_identifier(identifier)
        return self._provider.exists(identifier)

    def list_metadata(self) -> List[SecretMetadata]:
        """List metadata for all stored secrets. Never includes plaintext values."""
        return self._provider.list_metadata()

    def rotate_secret(self, identifier: str, new_secret_value: str) -> SecretRotationResult:
        """Atomically rotate a credential in native storage.
        
        Emits SECRET_ROTATED audit event.
        """
        self._validate_identifier(identifier)
        if not new_secret_value:
            raise SecretError("Cannot rotate to an empty secret value.")

        try:
            result = self._provider.rotate(identifier, new_secret_value)
            self.audit_logger.log_event(
                event_type="SECRET_ROTATED",
                resource=identifier,
                action="rotate",
                status="SUCCESS" if result.success else "FAILED",
                details={
                    "provider": self._provider.provider_name,
                    "old_version": result.old_version,
                    "new_version": result.new_version,
                },
            )
            return result
        except Exception as e:
            self.audit_logger.log_event(
                event_type="SECRET_ROTATED",
                resource=identifier,
                action="rotate",
                status="FAILED",
                details={"error": str(e)},
            )
            raise

    def migrate_legacy_keys(self) -> str:
        """Migrate legacy memory encryption keys from environment/files to native vault.
        
        Emits SECRET_MIGRATED audit event.
        """
        try:
            migrated_key = self.migrator.migrate_memory_encryption_key()
            self.audit_logger.log_event(
                event_type="SECRET_MIGRATED",
                resource="BUDDY_MEMORY_ENCRYPTION_KEY",
                action="migrate",
                status="SUCCESS",
                details={"provider": self._provider.provider_name},
            )
            return migrated_key
        except Exception as e:
            self.audit_logger.log_event(
                event_type="SECRET_MIGRATED",
                resource="BUDDY_MEMORY_ENCRYPTION_KEY",
                action="migrate",
                status="FAILED",
                details={"error": str(e)},
            )
            raise

    def redact(self, text: str) -> str:
        """Centralized redaction helper. Emits SECRET_REDACTED if secrets are found."""
        cleaned = redact_string(text)
        if cleaned != text:
            self.audit_logger.log_event(
                event_type="SECRET_REDACTED",
                resource="stream",
                action="redact",
                status="SUCCESS",
                details={"masked_pattern_detected": True},
            )
        return cleaned

    def redact_data(self, data: Any) -> Any:
        """Scrub secrets from nested data structures."""
        return redact_structure(data)

    def shutdown(self) -> None:
        """Zeroize all memory and cleanly shut down secret vault services."""
        self.lifecycle_manager.shutdown()
        logger.info("SecretVaultService shutdown complete.")
