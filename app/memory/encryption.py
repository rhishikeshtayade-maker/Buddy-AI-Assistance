"""BUDDY Long-Term Memory Encryption Subsystem.

Provides cryptographic abstractions for encrypting stored personal memory records
using authenticated encryption (Fernet / AES-CBC + HMAC-SHA256).
Enforces fail-closed behavior when encryption is enabled but keys are missing or invalid.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import base64
import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import BuddyConfig
from app.core.exceptions import MemoryEncryptionError

logger = logging.getLogger("buddy.memory.encryption")


class MemoryEncryptor(ABC):
    """Abstract interface for memory record field encryption and decryption."""

    @abstractmethod
    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext string into protected ciphertext."""
        ...

    @abstractmethod
    def decrypt(self, ciphertext: str) -> str:
        """Decrypt ciphertext back into plaintext."""
        ...


class NoOpMemoryEncryptor(MemoryEncryptor):
    """Pass-through encryptor used when memory encryption is disabled in configuration."""

    def encrypt(self, plaintext: str) -> str:
        return plaintext

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext


class FernetMemoryEncryptor(MemoryEncryptor):
    """Authenticated encryption backed by cryptography.fernet.Fernet (AES-128-CBC + HMAC-SHA256)."""

    def __init__(self, key: bytes) -> None:
        try:
            self._fernet = Fernet(key)
        except Exception as e:
            raise MemoryEncryptionError(f"Failed to initialize Fernet memory encryptor: {e}") from e

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        try:
            encrypted_bytes = self._fernet.encrypt(plaintext.encode("utf-8"))
            return encrypted_bytes.decode("utf-8")
        except Exception as e:
            raise MemoryEncryptionError(f"Memory encryption failed: {e}") from e

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        try:
            decrypted_bytes = self._fernet.decrypt(ciphertext.encode("utf-8"))
            return decrypted_bytes.decode("utf-8")
        except InvalidToken as it:
            raise MemoryEncryptionError("Memory decryption failed: Invalid token, key mismatch, or corrupt data.") from it
        except Exception as e:
            raise MemoryEncryptionError(f"Memory decryption failed: {e}") from e


def derive_key_from_passphrase(passphrase: str, salt: bytes = b"buddy_memory_salt_v1") -> bytes:
    """Derive a URL-safe 32-byte base64-encoded key from a passphrase using SHA-256."""
    derived = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 100_000)
    return base64.urlsafe_b64encode(derived)


def get_memory_encryptor(config: BuddyConfig) -> MemoryEncryptor:
    """Factory to construct the appropriate MemoryEncryptor based on application configuration.

    If memory_encryption_enabled is True:
    - Looks for an explicit key in config.memory_encryption_key
    - Or checks BUDDY_MEMORY_KEY env variable
    - Or checks data/.memory_key file
    - If no key is found, FAILS CLOSED by raising MemoryEncryptionError.
    """
    if not config.memory_encryption_enabled:
        return NoOpMemoryEncryptor()

    key_str = config.memory_encryption_key or os.environ.get("BUDDY_MEMORY_KEY")

    if not key_str:
        # Check local protected key file
        key_file = Path("data/.memory_key")
        if key_file.exists():
            try:
                key_str = key_file.read_text(encoding="utf-8").strip()
            except Exception as e:
                raise MemoryEncryptionError(f"Failed to read memory key file '{key_file}': {e}") from e

    if not key_str:
        # FAIL CLOSED: Never pretend to be encrypted if no key exists
        err_msg = (
            "Memory encryption is enabled, but no encryption key was provided. "
            "Set BUDDY_MEMORY_KEY or supply memory_encryption_key in config. Failing closed."
        )
        logger.critical(err_msg)
        raise MemoryEncryptionError(err_msg)

    # Validate or derive key
    try:
        raw_key = key_str.strip().encode("utf-8")
        # Try if already valid 32-byte base64 Fernet key
        Fernet(raw_key)
        return FernetMemoryEncryptor(raw_key)
    except Exception:
        # Derive valid key from passphrase
        derived = derive_key_from_passphrase(key_str)
        return FernetMemoryEncryptor(derived)
