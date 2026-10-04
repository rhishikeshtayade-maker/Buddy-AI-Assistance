"""BUDDY Legacy Credential & Memory Key Migration.

Migrates legacy environment variable keys (BUDDY_MEMORY_KEY) and file-based keys
into native Windows DPAPI / Credential Manager storage without plaintext leakage.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

from app.core.logging import get_logger
from app.security.secrets.exceptions import SecretMigrationError, SecretNotFoundError
from app.security.secrets.key_manager import BUDDY_MEMORY_ENCRYPTION_KEY, KeyManager
from app.security.secrets.provider import SecretProvider

logger = get_logger("security.secrets.migration")


class KeyMigrator:
    """Manages migration of legacy configuration keys into secure native storage."""

    def __init__(self, provider: SecretProvider) -> None:
        self.provider = provider
        self.key_manager = KeyManager(provider)

    def migrate_memory_encryption_key(
        self,
        legacy_env_var: str = "BUDDY_MEMORY_KEY",
        legacy_config_key: Optional[str] = None,
        legacy_file_path: Optional[Path] = Path("data/.memory_key"),
    ) -> str:
        """Migrate legacy memory key to native storage. Fails closed on corrupted data.

        Order of precedence:
        1. Native secure storage (already migrated or initialized)
        2. Legacy environment variable
        3. Legacy config key
        4. Legacy file storage
        5. Auto-generate new secure key if enabled
        """
        # 1. Check if native key exists
        try:
            native_key = self.provider.retrieve(BUDDY_MEMORY_ENCRYPTION_KEY)
            if native_key:
                logger.info("Found existing native memory encryption key in secure storage.")
                return native_key
        except SecretNotFoundError:
            pass
        except Exception as e:
            raise SecretMigrationError(f"Failed to query native vault for memory key: {e}") from e

        # 2. Look for legacy key sources (DO NOT LOG VALUES)
        legacy_source: Optional[str] = None
        legacy_val: Optional[str] = None

        if os.environ.get(legacy_env_var):
            legacy_val = os.environ.get(legacy_env_var)
            legacy_source = f"env:{legacy_env_var}"
        elif legacy_config_key:
            legacy_val = legacy_config_key
            legacy_source = "config:memory_encryption_key"
        elif legacy_file_path and legacy_file_path.exists():
            try:
                legacy_val = legacy_file_path.read_text(encoding="utf-8").strip()
                legacy_source = f"file:{legacy_file_path}"
            except Exception as e:
                raise SecretMigrationError(f"Failed to read legacy key file '{legacy_file_path}': {e}") from e

        # 3. If legacy key exists, validate and store into native vault
        if legacy_val:
            try:
                clean_key = legacy_val.strip()
                # Test validity with Fernet or derivation
                try:
                    Fernet(clean_key.encode("utf-8"))
                except Exception:
                    # Passphrase derivation
                    from app.memory.encryption import derive_key_from_passphrase
                    derived = derive_key_from_passphrase(clean_key)
                    clean_key = derived.decode("ascii")

                # Store into native vault
                self.provider.store(
                    identifier=BUDDY_MEMORY_ENCRYPTION_KEY,
                    secret_value=clean_key,
                    metadata={"description": f"Migrated from {legacy_source}"},
                )
                logger.info("Successfully migrated legacy memory key from %s into secure vault.", legacy_source)

                # Secure cleanup of legacy file if present
                if legacy_file_path and legacy_file_path.exists():
                    try:
                        legacy_file_path.unlink()
                        logger.info("Removed legacy plaintext key file '%s'.", legacy_file_path)
                    except Exception as e:
                        logger.warning("Could not delete legacy key file: %s", e)

                return clean_key

            except Exception as e:
                raise SecretMigrationError(f"Memory key migration failed (failing closed): {e}") from e

        # 4. No legacy key exists: generate a brand new secure native key
        logger.info("No legacy memory encryption key found. Generating fresh native key.")
        return self.key_manager.get_or_create_key(BUDDY_MEMORY_ENCRYPTION_KEY)
