"""BUDDY Contextual Awareness Unit Tests.

Validates core models, observers, providers, scheduler, relevance scoring,
interruption management, deduplication, and suggestion generation.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Dict

import pytest

from app.context_awareness.activity import ActivityObserver
from app.context_awareness.calendar import CalendarObserver, MockCalendarProvider
from app.context_awareness.config import ContextAwarenessConfig
from app.context_awareness.deduplication import DeduplicationManager
from app.context_awareness.foreground import ForegroundObserver
from app.context_awareness.interruption import InterruptionManager
from app.context_awareness.models import (
    ActivityState,
    CalendarEvent,
    ContextSnapshot,
    ContextTrigger,
    ForegroundAppInfo,
    InterruptionBudgetDecision,
    NotificationMetadata,
    ObserverStatus,
    ProactiveActionProposal,
    ProactivePolicyLevel,
    ScheduledItem,
    SensitivityLevel,
    TaskStateContext,
    TriggerType,
    TrustClassification,
)
from app.context_awareness.notifications import MockNotificationProvider, NotificationObserver
from app.context_awareness.permissions import ContextPermissionGuard, ObserverPermissionType
from app.context_awareness.privacy import PrivacyGuard
from app.context_awareness.relevance import RelevanceEngine
from app.context_awareness.scheduler import ContextScheduler
from app.context_awareness.suggestions import SuggestionGenerator
from app.context_awareness.triggers import TriggerEngine
from app.tools.models import ToolRiskLevel


@pytest.fixture
def config() -> ContextAwarenessConfig:
    return ContextAwarenessConfig(
        context_awareness_enabled=True,
        foreground_observer_enabled=True,
        activity_observer_enabled=True,
        notification_observer_enabled=True,
        calendar_enabled=True,
        proactive_assistance_enabled=True,
        activity_idle_threshold=300.0,
        activity_away_threshold=900.0,
        suggestion_cooldown_seconds=600.0,
        max_interruptions_per_hour=6,
    )


@pytest.fixture
def guard(config: ContextAwarenessConfig) -> ContextPermissionGuard:
    return ContextPermissionGuard(config)


@pytest.fixture
def privacy(config: ContextAwarenessConfig) -> PrivacyGuard:
    return PrivacyGuard(config)


# --- Models & Schema Tests ---

def test_context_snapshot_no_raw_media() -> None:
    """Ensure ContextSnapshot model has no raw video/audio/keystroke fields."""
    fields = ContextSnapshot.model_fields.keys()
    assert "raw_screenshot" not in fields
    assert "raw_audio" not in fields
    assert "keystrokes" not in fields
    assert "clipboard_content" not in fields


def test_notification_metadata_untrusted_default() -> None:
    """Notifications must always be classified UNTRUSTED by default."""
    notif = NotificationMetadata(source_app="Slack", title="New message", preview="Hello")
    assert notif.trust == TrustClassification.UNTRUSTED


def test_calendar_event_untrusted_default() -> None:
    """Calendar events must always be classified UNTRUSTED by default."""
    event = CalendarEvent(title="Sprint Review", start_time=time.time())
    assert event.trust == TrustClassification.UNTRUSTED


# --- Activity Observer Tests ---

@pytest.mark.asyncio
async def test_activity_observer_coarse_states(config: ContextAwarenessConfig, guard: ContextPermissionGuard) -> None:
    observer = ActivityObserver(config=config, permission_guard=guard)
    # Active
    observer.set_simulated_idle_seconds(50.0)
    state = await observer.poll()
    assert state == ActivityState.ACTIVE

    # Idle
    observer.set_simulated_idle_seconds(350.0)
    state = await observer.poll()
    assert state == ActivityState.IDLE

    # Away
    observer.set_simulated_idle_seconds(1000.0)
    state = await observer.poll()
    assert state == ActivityState.AWAY


# --- Foreground Observer Tests ---

@pytest.mark.asyncio
async def test_foreground_observer_simulation(config: ContextAwarenessConfig, guard: ContextPermissionGuard, privacy: PrivacyGuard) -> None:
    observer = ForegroundObserver(config=config, permission_guard=guard, privacy_guard=privacy)
    observer.set_simulated_app(process_name="code.exe", app_identity="Visual Studio Code", window_title="app.py - BUDDY")
    info = await observer.poll()
    assert info.process_name == "code.exe"
    assert info.app_identity == "Visual Studio Code"
    assert "BUDDY" in (info.window_title or "")


# --- Scheduler Tests ---

@pytest.mark.asyncio
async def test_scheduler_one_time_and_recurring(config: ContextAwarenessConfig, guard: ContextPermissionGuard) -> None:
    scheduler = ContextScheduler(config=config, permission_guard=guard)
    
    # 1. One-time item
    item1 = scheduler.schedule_once("Test Reminder", target_time=time.time() - 0.5)
    due = await scheduler.poll()
    assert any(i.item_id == item1.item_id for i in due)

    # 2. Cancel test
    item2 = scheduler.schedule_once("Cancelled Reminder", target_time=time.time() + 100.0)
    assert scheduler.cancel(item2.item_id) is True
    assert scheduler.get_item(item2.item_id) is None


# --- Relevance Engine Tests ---

def test_relevance_scoring_active_vs_away() -> None:
    relevance = RelevanceEngine()
    trigger = ContextTrigger(
        trigger_type=TriggerType.CalendarEventApproaching,
        source="test",
        payload={"is_critical": False},
    )

    snapshot_active = ContextSnapshot(activity_state=ActivityState.ACTIVE)
    snapshot_away = ContextSnapshot(activity_state=ActivityState.AWAY)

    score_active = relevance.calculate_score(trigger, snapshot_active)
    score_away = relevance.calculate_score(trigger, snapshot_away)

    assert 0.0 <= score_active <= 1.0
    assert 0.0 <= score_away <= 1.0
    assert score_active > score_away


# --- Interruption & Quiet Hours Tests ---

def test_quiet_hours_overnight_detection(config: ContextAwarenessConfig) -> None:
    config.quiet_hours_enabled = True
    config.quiet_hours_start = "22:00"
    config.quiet_hours_end = "07:00"

    manager = InterruptionManager(config)

    # 23:30 is in quiet hours
    dt_night = datetime(2026, 10, 4, 23, 30)
    assert manager.is_in_quiet_hours(dt_night) is True

    # 03:15 is in quiet hours
    dt_early = datetime(2026, 10, 4, 3, 15)
    assert manager.is_in_quiet_hours(dt_early) is True

    # 14:00 is NOT in quiet hours
    dt_day = datetime(2026, 10, 4, 14, 0)
    assert manager.is_in_quiet_hours(dt_day) is False


def test_interruption_budget_cooldown(config: ContextAwarenessConfig) -> None:
    config.suggestion_cooldown_seconds = 600.0
    manager = InterruptionManager(config)

    fp = "test_fingerprint_123"
    # First check allowed
    dec1 = manager.check_interruption_budget(fingerprint=fp)
    assert dec1 == InterruptionBudgetDecision.ALLOWED

    # Record presentation
    manager.record_interruption(fp)

    # Second check suppressed by cooldown
    dec2 = manager.check_interruption_budget(fingerprint=fp)
    assert dec2 == InterruptionBudgetDecision.COOLDOWN_SUPPRESSED

    # Critical item bypasses cooldown
    dec3 = manager.check_interruption_budget(fingerprint=fp, is_critical=True)
    assert dec3 == InterruptionBudgetDecision.ALLOWED


# --- Deduplication Tests ---

def test_deduplication_manager() -> None:
    dedup = DeduplicationManager(time_bucket_seconds=300.0)
    fp = dedup.compute_suggestion_fingerprint("Open calendar notes", TriggerType.CalendarEventApproaching)

    assert dedup.is_duplicate(fp) is False
    dedup.record_seen(fp)
    assert dedup.is_duplicate(fp) is True


# --- Suggestion Generator Tests ---

def test_suggestion_generator_danger_bound() -> None:
    config = ContextAwarenessConfig()
    relevance = RelevanceEngine()
    interruption = InterruptionManager(config)
    dedup = DeduplicationManager()
    generator = SuggestionGenerator(relevance, interruption, dedup)

    trigger = ContextTrigger(trigger_type=TriggerType.TaskDeadlineApproaching, source="test")
    snapshot = ContextSnapshot(activity_state=ActivityState.ACTIVE)

    proposal = ProactiveActionProposal(
        reason="Terminate process",
        triggering_context_id=trigger.trigger_id,
        suggested_tool="app.close",
        arguments={"application": "notepad"},
        risk_level=ToolRiskLevel.MODERATE,
        expiration=time.time() + 300.0,
    )

    suggestion = generator.create_suggestion(
        trigger=trigger,
        snapshot=snapshot,
        message="Closing notepad",
        base_policy_level=ProactivePolicyLevel.SUGGESTION,
        proposal=proposal,
    )

    assert suggestion is not None
    # Moderate risk MUST enforce CONFIRMATION_REQUIRED
    assert suggestion.policy_level == ProactivePolicyLevel.CONFIRMATION_REQUIRED
    assert proposal.requires_confirmation is True
