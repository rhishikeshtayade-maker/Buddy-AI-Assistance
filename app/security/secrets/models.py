"""BUDDY Secure Secrets & Credential Models.

Provides strongly typed metadata models, secret wrappers, and audit representations.
Guarantees that __repr__ and __str__ never disclose secret values.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class SecretSensitivity(str, Enum):
    """Sensitivity level classification for stored credentials."""

    NORMAL = "normal"
    SENSITIVE = "sensitive"
    HIGHLY_SENSITIVE = "highly_sensitive"
    CRITICAL = "critical"


class SecretAccessType(str, Enum):
    """Distinguishes between internal usage of a secret vs external disclosure."""

    SECRET_USE = "secret_use"                 # Allowed: provider uses secret internally (e.g. HTTP Authorization)
    SECRET_DISCLOSURE = "secret_disclosure"   # Forbidden in ordinary conversation: displaying raw plaintext secret


class SecretProviderType(str, Enum):
    """Underlying native secure storage backend."""

    WINDOWS_DPAPI = "windows_dpapi"
    WINDOWS_CRED_MGR = "windows_cred_mgr"
    MOCK = "mock"
    HYBRID = "hybrid"


class SecretMetadata(BaseModel):
    """Metadata describing a stored secret without revealing its plaintext value."""

    identifier: str = Field(..., description="Opaque secret identifier, e.g. BUDDY_OPENAI_API_KEY")
    provider: str = Field(..., description="Provider backend that manages the secret")
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    rotation_required: bool = Field(default=False)
    sensitivity: SecretSensitivity = Field(default=SecretSensitivity.HIGHLY_SENSITIVE)
    version: int = Field(default=1)
    description: Optional[str] = Field(default=None)

    def __repr__(self) -> str:
        return f"<SecretMetadata identifier='{self.identifier}' provider='{self.provider}' version={self.version}>"

    def __str__(self) -> str:
        return self.__repr__()


class SecretContainer:
    """In-memory wrapper for sensitive plaintext secrets with zeroization support and disclosure protection.

    Guarantees that repr() and str() never expose the underlying secret string.
    """

    def __init__(self, identifier: str, value: str, metadata: Optional[SecretMetadata] = None) -> None:
        self._identifier = identifier
        self._value: Optional[str] = value
        self._metadata = metadata or SecretMetadata(
            identifier=identifier,
            provider="container",
        )
        self._created_at = time.time()
        self._destroyed = False

    @property
    def identifier(self) -> str:
        return self._identifier

    @property
    def metadata(self) -> SecretMetadata:
        return self._metadata

    @property
    def is_destroyed(self) -> bool:
        return self._destroyed

    def get_secret_value(self) -> str:
        """Access raw secret value for internal provider operations."""
        if self._destroyed or self._value is None:
            raise RuntimeError(f"Secret '{self._identifier}' has been zeroized or destroyed.")
        return self._value

    def zeroize(self) -> None:
        """Best-effort zeroization of plaintext secret in memory.

        Note: Python's immutable strings cannot guarantee hardware-level RAM erasure,
        but references are discarded and flags cleared to prevent accidental leakage.
        """
        self._value = None
        self._destroyed = True

    def __enter__(self) -> SecretContainer:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.zeroize()

    def __repr__(self) -> str:
        return f"<SecretContainer identifier='{self._identifier}' [VALUE PROTECTED]>"

    def __str__(self) -> str:
        return self.__repr__()


class SecretRotationResult(BaseModel):
    """Outcome of an atomic secret rotation operation."""

    identifier: str
    success: bool
    old_version: int
    new_version: int
    timestamp: float = Field(default_factory=time.time)
    message: str = "Secret rotated successfully"
