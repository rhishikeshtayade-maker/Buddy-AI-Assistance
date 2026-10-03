"""BUDDY Core Exception Hierarchy.

Defines typed exceptions for runtime errors, state machine violations,
service registry issues, configuration errors, and lifecycle failures.
"""

from typing import Optional


class BuddyError(Exception):
    """Base exception for all BUDDY runtime errors."""

    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class StateTransitionError(BuddyError):
    """Raised when an illegal or unsupported state transition is attempted."""

    def __init__(
        self,
        from_state: str,
        to_state: str,
        message: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> None:
        msg = message or f"Illegal state transition: '{from_state}' -> '{to_state}'"
        d = details or {}
        d.update({"from_state": from_state, "to_state": to_state})
        super().__init__(msg, details=d)
        self.from_state = from_state
        self.to_state = to_state


class ServiceRegistryError(BuddyError):
    """Base exception for service registry failures."""


class ServiceNotFoundError(ServiceRegistryError):
    """Raised when attempting to retrieve an unregistered service."""

    def __init__(self, service_key: str) -> None:
        super().__init__(
            f"Service '{service_key}' not found in service registry.",
            details={"service_key": service_key},
        )
        self.service_key = service_key


class DuplicateServiceError(ServiceRegistryError):
    """Raised when attempting to register a duplicate service without override permission."""

    def __init__(self, service_key: str) -> None:
        super().__init__(
            f"Service '{service_key}' is already registered in registry.",
            details={"service_key": service_key},
        )
        self.service_key = service_key


class ConfigurationError(BuddyError):
    """Raised when application configuration is missing, invalid, or malformed."""


class HealthCheckError(BuddyError):
    """Raised when a health check encounters an unhandled runtime error."""


class LifecycleError(BuddyError):
    """Raised when application lifecycle violates sequential ordering or fails to start."""


class SecurityError(BuddyError):
    """Base exception for security boundary violations."""


class PathSecurityError(SecurityError):
    """Raised when a file or directory path violates path policy constraints."""


class PermissionDeniedError(SecurityError):
    """Raised when an operation is rejected by the permission engine."""


class ConfirmationError(SecurityError):
    """Raised when a confirmation token is invalid, expired, mismatched, or replayed."""


class AuthenticationError(SecurityError):
    """Raised when authentication challenge fails or is required."""


class ToolExecutionError(BuddyError):
    """Raised when tool execution encounters an error."""


class ToolNotFoundError(BuddyError):
    """Raised when attempting to execute an unregistered tool."""


class ToolTimeoutError(ToolExecutionError):
    """Raised when a tool execution exceeds its configured timeout."""


class VerificationError(ToolExecutionError):
    """Raised when post-execution verification fails to empirically confirm expected system state."""


class ValidationError(BuddyError):
    """Raised when structured input, plan, or configuration fails validation."""


class MemorySubsystemError(BuddyError):
    """Base exception for all memory subsystem errors."""


class MemoryStorageError(MemorySubsystemError):
    """Raised when memory database or store operation fails."""


class MemoryPolicyViolationError(MemorySubsystemError):
    """Raised when content violates memory storage policy (e.g. secret detected)."""


class MemorySecurityError(SecurityError):
    """Raised when an operation attempts to bypass memory security or authorization."""


class MemoryEncryptionError(MemorySubsystemError, SecurityError):
    """Raised when memory encryption or decryption fails."""


# Compatibility alias
RegistryError = ServiceRegistryError
BuddyMemoryError = MemorySubsystemError
