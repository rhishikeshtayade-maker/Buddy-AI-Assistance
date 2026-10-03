"""BUDDY Core Runtime Subsystem.

Exposes state machine, event bus, typed configuration, service registry,
health monitoring, structured logging, and application lifecycle.
"""

from app.core.config import BuddyConfig
from app.core.context import RuntimeContext
from app.core.events import (
    ApplicationStartedEvent,
    ApplicationStoppedEvent,
    ApplicationStoppingEvent,
    BaseEvent,
    ErrorEvent,
    EventBus,
    HealthChangedEvent,
    StateChangedEvent,
)
from app.core.exceptions import (
    BuddyError,
    ConfigurationError,
    DuplicateServiceError,
    HealthCheckError,
    LifecycleError,
    ServiceNotFoundError,
    ServiceRegistryError,
    StateTransitionError,
)
from app.core.health import (
    HealthCheckResult,
    HealthManager,
    HealthStatus,
    SystemHealthResult,
)
from app.core.lifecycle import LifecycleManager
from app.core.logging import (
    REDACTED_MASK,
    BuddyLogFormatter,
    SecretRedactionFilter,
    get_logger,
    redact_string,
    setup_logging,
)
from app.core.registry import ServiceRegistry
from app.core.state import (
    VALID_TRANSITIONS,
    BuddyState,
    StateMachine,
    StateTransitionRecord,
)

__all__ = [
    # State Machine
    "BuddyState",
    "StateMachine",
    "StateTransitionRecord",
    "VALID_TRANSITIONS",
    # Events & Bus
    "BaseEvent",
    "ApplicationStartedEvent",
    "ApplicationStoppingEvent",
    "ApplicationStoppedEvent",
    "StateChangedEvent",
    "ErrorEvent",
    "HealthChangedEvent",
    "EventBus",
    # Config
    "BuddyConfig",
    # Registry
    "ServiceRegistry",
    # Health
    "HealthStatus",
    "HealthCheckResult",
    "SystemHealthResult",
    "HealthManager",
    # Logging
    "setup_logging",
    "get_logger",
    "redact_string",
    "SecretRedactionFilter",
    "BuddyLogFormatter",
    "REDACTED_MASK",
    # Context & Lifecycle
    "RuntimeContext",
    "LifecycleManager",
    # Exceptions
    "BuddyError",
    "StateTransitionError",
    "ServiceRegistryError",
    "ServiceNotFoundError",
    "DuplicateServiceError",
    "ConfigurationError",
    "HealthCheckError",
    "LifecycleError",
]
