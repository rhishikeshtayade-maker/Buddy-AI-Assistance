"""BUDDY Local Authentication Boundary.

Provides an abstraction for verifying local authorization credentials (e.g. PIN, OS credentials)
before high-risk or critical operations are executed.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from abc import ABC, abstractmethod
from typing import Optional

from app.core.exceptions import AuthenticationError

logger = logging.getLogger("buddy.security.auth")


class Authenticator(ABC):
    """Abstract interface for local user authentication."""

    @abstractmethod
    async def authenticate(self, challenge: str, credential: Optional[str] = None) -> bool:
        """Evaluate authentication credential against local security policy.

        Args:
            challenge: Descriptive reason or operation requiring authentication.
            credential: PIN, password, or security token provided by user.

        Returns:
            True if authentication succeeds; False otherwise.
        """
        ...


class MockAuthenticator(Authenticator):
    """Deterministic mock authenticator for testing and continuous integration."""

    def __init__(self, should_succeed: bool = True) -> None:
        self.should_succeed = should_succeed
        self.last_challenge: Optional[str] = None
        self.call_count: int = 0

    async def authenticate(self, challenge: str, credential: Optional[str] = None) -> bool:
        self.last_challenge = challenge
        self.call_count += 1
        # Never log credential
        logger.debug("MockAuthenticator challenge: '%s' -> %s", challenge, self.should_succeed)
        return self.should_succeed


class PinAuthenticator(Authenticator):
    """Local PIN authenticator using salted PBKDF2-HMAC-SHA256.

    Security Guarantee:
    - Never stores plaintext PINs.
    - Never writes credentials to log files.
    - Uses constant-time comparison to prevent timing attacks.
    """

    def __init__(self, pin_hash_hex: Optional[str] = None, salt: Optional[bytes] = None) -> None:
        self._salt = salt or os.urandom(16)
        self._pin_hash = pin_hash_hex

    @classmethod
    def create_with_pin(cls, pin: str) -> PinAuthenticator:
        """Factory creating an authenticator with a hashed PIN."""
        salt = os.urandom(16)
        derived = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 100_000)
        return cls(pin_hash_hex=derived.hex(), salt=salt)

    async def authenticate(self, challenge: str, credential: Optional[str] = None) -> bool:
        if not self._pin_hash or not credential:
            logger.warning("Authentication rejected: missing PIN hash or credential.")
            return False

        # Hash candidate credential with salt
        derived = hashlib.pbkdf2_hmac("sha256", credential.encode("utf-8"), self._salt, 100_000)
        # Constant-time comparison
        valid = hmac.compare_digest(derived.hex(), self._pin_hash)
        logger.info("PIN authentication evaluated for challenge: '%s' (success=%s)", challenge, valid)
        return valid
