"""BUDDY Security Subsystem.

Provides permissions, user confirmation, authentication, path sandboxing,
interaction policies, and audit logging.
"""

from app.security.audit import AuditLogger, AuditRecord
from app.security.authentication import Authenticator, MockAuthenticator, PinAuthenticator
from app.security.confirmation import ConfirmationManager, ConfirmationToken
from app.security.interaction_policy import (
    ALLOWED_KEYS,
    PROTECTED_APPLICATIONS,
    InteractionPolicy,
    InteractionSecurityError,
)
from app.security.path_policy import PathPolicy
from app.security.permissions import PermissionDecision, PermissionEngine

__all__ = [
    "AuditLogger",
    "AuditRecord",
    "Authenticator",
    "MockAuthenticator",
    "PinAuthenticator",
    "ConfirmationManager",
    "ConfirmationToken",
    "PathPolicy",
    "PermissionDecision",
    "PermissionEngine",
    "InteractionPolicy",
    "InteractionSecurityError",
    "ALLOWED_KEYS",
    "PROTECTED_APPLICATIONS",
]
