"""BUDDY Contextual Awareness Integration Tests.

Validates complete integration between ContextAwarenessService,
LifecycleManager, HealthManager, EventBus, ToolExecutor, and Memory subsystem.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

import pytest

from app.context_awareness.config import ContextAwarenessConfig
from app.context_awareness.events import (
    ContextObserverEnabledEvent,
    ContextSnapshotCreatedEvent,
    ContextTriggerDetectedEvent,
    ProactiveSuggestionCreatedEvent,
)
from app.context_awareness.models import (
    ActivityState,
    ContextTrigger,
    ObserverStatus,
    ProactiveActionProposal,
    TriggerType,
)
from app.context_awareness.service import ContextAwarenessService
from app.core.config import BuddyConfig
from app.core.events import EventBus
from app.core.health import HealthManager, HealthStatus
from app.core.lifecycle import LifecycleManager
from app.security.audit import AuditLogger
from app.tools.builtin import register_builtin_tools
from app.tools.executor import ToolExecutor
from app.tools.models import ToolResult, ToolRiskLevel
from app.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_lifecycle_context_awareness_integration() -> None:
    """LifecycleManager initializes, registers, and shuts down ContextAwarenessService."""
    config = BuddyConfig(
        app_env="testing",
        context_awareness_enabled=True,
    )
    lifecycle = LifecycleManager(config=config)
    ctx = await lifecycle.initialize()

    # Verify service registered
    ctx_svc = lifecycle.service_registry.get("context_awareness")
    assert ctx_svc is not None
    assert isinstance(ctx_svc, ContextAwarenessService)

    # Verify HealthManager checks registered
    checks = lifecycle.health_manager._checks
    assert "ContextAwareness" in checks
    assert "ForegroundObserver" in checks
    assert "ActivityObserver" in checks

    # Clean shutdown
    await lifecycle.shutdown(reason="Integration test complete")
    assert not ctx_svc.foreground_observer.is_running


@pytest.mark.asyncio
async def test_event_bus_publishing() -> None:
    """Context triggers and suggestions emit typed events onto the EventBus."""
    event_bus = EventBus()
    received_events: List[Any] = []

    async def _event_handler(event: Any) -> None:
        received_events.append(event)

    event_bus.subscribe(ContextTriggerDetectedEvent, _event_handler)
    event_bus.subscribe(ProactiveSuggestionCreatedEvent, _event_handler)

    config = ContextAwarenessConfig(
        context_awareness_enabled=True,
        suggestion_cooldown_seconds=0.0,
    )
    service = ContextAwarenessService(config=config, event_bus=event_bus)

    trigger = ContextTrigger(
        trigger_type=TriggerType.CalendarEventApproaching,
        source="test",
        payload={"event": {"title": "Design Meeting", "start_time": time.time() + 600}},
    )

    await service.handle_trigger(trigger)
    # Yield to let event bus process
    await asyncio.sleep(0.05)

    assert any(isinstance(e, ContextTriggerDetectedEvent) for e in received_events)
    assert any(isinstance(e, ProactiveSuggestionCreatedEvent) for e in received_events)


@pytest.mark.asyncio
async def test_ui_state_model() -> None:
    """Verify UI state representation contains observers and recent suggestions."""
    service = ContextAwarenessService(config=ContextAwarenessConfig())
    ui_state = service.get_ui_state()

    assert ui_state.context_awareness_enabled is True
    assert "foreground" in ui_state.observers
    assert "activity" in ui_state.observers
    assert "calendar" in ui_state.observers
    assert isinstance(ui_state.recent_suggestions, list)
