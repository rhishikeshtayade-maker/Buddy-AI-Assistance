"""BUDDY Runtime Context.

Provides controlled, unified access to core services without relying on
opaque global state or uncontrolled singletons.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.core.config import BuddyConfig
    from app.core.events import EventBus
    from app.core.health import HealthManager
    from app.core.lifecycle import LifecycleManager
    from app.core.registry import ServiceRegistry
    from app.core.state import StateMachine


@dataclass
class RuntimeContext:
    """Encapsulates the core runtime dependencies and services for BUDDY."""

    config: "BuddyConfig"
    event_bus: "EventBus"
    state_machine: "StateMachine"
    service_registry: "ServiceRegistry"
    health_manager: "HealthManager"
    logger: logging.Logger
    lifecycle: Optional["LifecycleManager"] = None

    def get_service(self, key: Any) -> Any:
        """Helper to fetch a registered service from the context registry."""
        return self.service_registry.get(key)
