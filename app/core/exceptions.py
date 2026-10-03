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
