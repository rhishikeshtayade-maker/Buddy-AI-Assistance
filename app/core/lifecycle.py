"""BUDDY Application Lifecycle Manager & Global Exception Coordination.

Orchestrates sequential startup, health verification, graceful shutdown,
signal handling (including Windows console events), and idempotent cleanup.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Optional

from app import __version__
from app.core.config import BuddyConfig
from app.core.context import RuntimeContext
from app.core.events import (
    ApplicationStartedEvent,
    ApplicationStoppedEvent,
    ApplicationStoppingEvent,
    ErrorEvent,
    EventBus,
    StateChangedEvent,
)
from app.core.exceptions import BuddyError, LifecycleError
from app.core.health import (
    HealthManager,
    HealthStatus,
    SystemHealthResult,
    create_config_health_check,
    create_event_bus_health_check,
    create_runtime_health_check,
    create_service_registry_health_check,
)
from app.core.logging import get_logger, setup_logging
from app.core.registry import ServiceRegistry
from app.core.state import BuddyState, StateMachine


class LifecycleManager:
    """Manages full lifecycle execution, error interception, and graceful shutdown."""

    def __init__(self, config: Optional[BuddyConfig] = None) -> None:
        self._config = config or BuddyConfig.load_from_env()
        self._logger = get_logger("core.lifecycle")
        self._service_registry = ServiceRegistry()
        self._event_bus = EventBus()
        self._state_machine = StateMachine(BuddyState.STARTING)
        self._health_manager = HealthManager()
        self._context: Optional[RuntimeContext] = None

        self._is_initialized = False
        self._is_running = False
        self._is_stopped = False
        self._shutdown_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()

        # Connect state machine transitions to event bus publishing
        self._state_machine.set_transition_callback(self._on_state_transition)

    @property
    def context(self) -> RuntimeContext:
        """Access the initialized RuntimeContext."""
        if self._context is None:
            raise LifecycleError("Runtime context accessed before initialization.")
        return self._context

    @property
    def state_machine(self) -> StateMachine:
        return self._state_machine

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    @property
    def health_manager(self) -> HealthManager:
        return self._health_manager

    @property
    def service_registry(self) -> ServiceRegistry:
        return self._service_registry

    @property
    def config(self) -> BuddyConfig:
        return self._config

    @property
    def is_running(self) -> bool:
        return self._is_running

    def _on_state_transition(
        self,
        prev_state: BuddyState,
        new_state: BuddyState,
        reason: str,
        timestamp: float,
    ) -> None:
        """Relay state changes onto the event bus."""
        event = StateChangedEvent(
            timestamp=timestamp,
            previous_state=prev_state,
            new_state=new_state,
            reason=reason,
        )
        self._event_bus.publish_sync(event)

    async def handle_error(
        self,
        error: BaseException,
        fatal: bool = False,
        reason: str = "Unhandled runtime error",
    ) -> None:
        """Centralized exception handling with logging, event emission, and error state."""
        error_type = type(error).__name__
        msg = str(error)
        self._logger.error(
            "Global Error Caught [%s]: %s (fatal=%s)",
            error_type,
            msg,
            fatal,
            exc_info=error,
        )

        current_st = self._state_machine.current_state

        # Emit ErrorEvent
        error_event = ErrorEvent(
            error_type=error_type,
            message=msg,
            state=current_st,
            fatal=fatal,
            details={"reason": reason},
        )
        await self._event_bus.publish(error_event)

        # Transition to ERROR if allowed from current state
        if self._state_machine.can_transition_to(BuddyState.ERROR):
            try:
                self._state_machine.transition_to(BuddyState.ERROR, reason=f"{error_type}: {msg}")
            except Exception as e:
                self._logger.warning("Could not transition to ERROR state: %s", e)

        if fatal:
            await self.shutdown(reason=f"Fatal error: {error_type}")

    async def initialize(self) -> RuntimeContext:
        """Initialize all core subsystems and verify base dependencies.

        Flow: STARTING -> Register Services -> Setup Health Checks -> Ready for IDLE
        """
        if self._is_initialized:
            self._logger.debug("Lifecycle already initialized.")
            return self.context

        try:
            # 1. Setup logging system
            setup_logging(self._config.log_level)
            self._logger.info("Initializing BUDDY Core Runtime (env=%s)...", self._config.app_env)

            # 2. Register core services in service registry
            self._service_registry.register(BuddyConfig, self._config)
            self._service_registry.register("config", self._config)
            self._service_registry.register(EventBus, self._event_bus)
            self._service_registry.register("event_bus", self._event_bus)
            self._service_registry.register(StateMachine, self._state_machine)
            self._service_registry.register("state_machine", self._state_machine)
            self._service_registry.register(HealthManager, self._health_manager)
            self._service_registry.register("health_manager", self._health_manager)
            self._service_registry.register(logging.Logger, self._logger)
            self._service_registry.register("logger", self._logger)

            # 3. Setup core health checks
            self._health_manager.register_check(
                "configuration", create_config_health_check(self._config)
            )
            self._health_manager.register_check(
                "event_bus", create_event_bus_health_check(self._event_bus)
            )
            self._health_manager.register_check(
                "service_registry", create_service_registry_health_check(self._service_registry)
            )
            self._health_manager.register_check("runtime", create_runtime_health_check())

            # 4. Create RuntimeContext
            self._context = RuntimeContext(
                config=self._config,
                event_bus=self._event_bus,
                state_machine=self._state_machine,
                service_registry=self._service_registry,
                health_manager=self._health_manager,
                logger=self._logger,
                lifecycle=self,
            )
            self._service_registry.register(RuntimeContext, self._context)
            self._service_registry.register("context", self._context)

            self._is_initialized = True
            self._logger.info("BUDDY Core Runtime services registered successfully.")
            return self._context

        except Exception as err:
            await self.handle_error(err, fatal=True, reason="Initialization failure")
            raise

    async def start(self) -> SystemHealthResult:
        """Run health checks and transition from STARTING -> IDLE."""
        if not self._is_initialized:
            await self.initialize()

        if self._state_machine.current_state != BuddyState.STARTING:
            raise LifecycleError(
                f"Cannot start from state {self._state_machine.current_state.value}"
            )

        try:
            # Run diagnostics
            health_report = await self._health_manager.run_all_checks()
            if health_report.status == HealthStatus.UNHEALTHY:
                self._logger.error("Core health check failed during startup: %s", health_report.checks)
                raise LifecycleError("System health check is UNHEALTHY during startup")

            # Transition STARTING -> IDLE
            self._state_machine.transition_to(BuddyState.IDLE, reason="Startup health verification passed")
            self._is_running = True

            # Emit ApplicationStartedEvent
            await self._event_bus.publish(
                ApplicationStartedEvent(
                    app_name=self._config.buddy_name,
                    version=__version__,
                    environment=self._config.app_env,
                )
            )
            self._logger.info("BUDDY is ready. State: %s", self._state_machine.current_state.value)
            return health_report

        except Exception as err:
            await self.handle_error(err, fatal=True, reason="Start failure")
            raise

    async def run(self) -> None:
        """Run the main event loop until shutdown is signaled."""
        if not self._is_running:
            await self.start()

        self._setup_signal_handlers()
        try:
            await self._stop_event.wait()
        finally:
            await self.shutdown(reason="Run loop terminated")

    def _setup_signal_handlers(self) -> None:
        """Register graceful shutdown hooks for Windows and POSIX signals."""
        def _signal_handler(sig_name: str) -> None:
            self._logger.info("Termination signal received: %s. Initiating graceful shutdown...", sig_name)
            self.stop()

        # Handle SIGINT (Ctrl+C)
        try:
            signal.signal(signal.SIGINT, lambda s, f: _signal_handler("SIGINT"))
        except (ValueError, AttributeError):
            pass

        # Handle SIGTERM
        try:
            signal.signal(signal.SIGTERM, lambda s, f: _signal_handler("SIGTERM"))
        except (ValueError, AttributeError):
            pass

        # Handle SIGBREAK on Windows
        if hasattr(signal, "SIGBREAK"):
            try:
                signal.signal(signal.SIGBREAK, lambda s, f: _signal_handler("SIGBREAK"))
            except (ValueError, AttributeError):
                pass

    def stop(self) -> None:
        """Signal the running loop to terminate."""
        self._stop_event.set()
        self._is_running = False

    async def shutdown(self, reason: str = "Graceful shutdown") -> None:
        """Idempotent graceful shutdown sequence.

        Flow: Any State -> SHUTTING_DOWN -> Cleanup Services -> Terminal Stopped
        Calling shutdown repeatedly is safe and will not crash.
        """
        async with self._shutdown_lock:
            if self._is_stopped:
                return

            self._logger.info("BUDDY Core Runtime shutting down: %s", reason)
            self._stop_event.set()
            self._is_running = False

            # Transition to SHUTTING_DOWN if permitted
            if self._state_machine.can_transition_to(BuddyState.SHUTTING_DOWN):
                try:
                    self._state_machine.transition_to(BuddyState.SHUTTING_DOWN, reason=reason)
                except Exception as e:
                    self._logger.warning("Error transitioning to SHUTTING_DOWN: %s", e)

            # Yield to event loop to allow pending StateChangedEvent dispatch
            await asyncio.sleep(0)

            # Publish stopping event
            try:
                await self._event_bus.publish(ApplicationStoppingEvent(reason=reason))
            except Exception as e:
                self._logger.warning("Error publishing ApplicationStoppingEvent: %s", e)

            # Cleanup event bus
            try:
                await self._event_bus.shutdown()
            except Exception as e:
                self._logger.warning("Error shutting down EventBus: %s", e)

            # Mark stopped
            self._is_stopped = True

            # Publish stopped event
            try:
                stopped_event = ApplicationStoppedEvent(exit_code=0)
                # EventBus is shut down, but log completion
                self._logger.info("BUDDY Core Runtime cleanup complete. (exit_code=%d)", stopped_event.exit_code)
            except Exception:
                pass
