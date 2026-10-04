"""BUDDY Contextual Awareness & Proactive Assistance Orchestration Service.

Coordinates:
- Observers (Foreground, Activity, Notifications, Calendar, Scheduler)
- Privacy Guard (Sensitive app suppression, redaction, ephemeral retention)
- Trigger Engine & Relevance Engine (Deterministic suggestion candidates)
- Interruption Management (Quiet hours, budget, cooldowns, deduplication)
- Proactive Action Dispatching (Exclusively through ToolRegistry and ToolExecutor)
- Memory, Browser, Vision, Voice, and Agent integrations
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from app.context_awareness.activity import ActivityObserver
from app.context_awareness.calendar import CalendarObserver, CalendarProvider, MockCalendarProvider
from app.context_awareness.config import ContextAwarenessConfig
from app.context_awareness.deduplication import DeduplicationManager
from app.context_awareness.events import (
    ContextObserverDisabledEvent,
    ContextObserverEnabledEvent,
    ContextPrivacyFilterTriggeredEvent,
    ContextSnapshotCreatedEvent,
    ContextTriggerDetectedEvent,
    InterruptionCooldownEvent,
    ProactiveActionBlockedEvent,
    ProactiveActionProposedEvent,
    ProactiveActionRequiresConfirmationEvent,
    ProactiveSuggestionCreatedEvent,
    ProactiveSuggestionSuppressedEvent,
    QuietHoursSuppressionEvent,
)
from app.context_awareness.foreground import ForegroundObserver
from app.context_awareness.interruption import InterruptionManager
from app.context_awareness.models import (
    ActivityState,
    BrowserContextInfo,
    CalendarEvent,
    ContextAwarenessUIState,
    ContextSnapshot,
    ContextTrigger,
    ContextualSuggestion,
    ForegroundAppInfo,
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
from app.context_awareness.notifications import MockNotificationProvider, NotificationObserver, NotificationProvider
from app.context_awareness.permissions import ContextPermissionGuard, ObserverPermissionType
from app.context_awareness.privacy import PrivacyGuard
from app.context_awareness.proactive import ProactiveActionDispatcher
from app.context_awareness.registry import ContextRegistry
from app.context_awareness.relevance import RelevanceEngine
from app.context_awareness.scheduler import ContextScheduler
from app.context_awareness.suggestions import SuggestionGenerator
from app.context_awareness.triggers import TriggerEngine
from app.core.events import EventBus
from app.core.health import HealthCheckResult, HealthManager, HealthStatus
from app.core.logging import get_logger
from app.security.audit import AuditLogger
from app.tools.executor import ToolExecutor
from app.tools.models import ToolResult, ToolRiskLevel

logger = get_logger("context.service")


class ContextAwarenessService:
    """Main coordinator for environmental awareness and proactive assistance."""

    def __init__(
        self,
        config: Optional[ContextAwarenessConfig] = None,
        event_bus: Optional[EventBus] = None,
        health_manager: Optional[HealthManager] = None,
        audit_logger: Optional[AuditLogger] = None,
        tool_executor: Optional[ToolExecutor] = None,
        calendar_provider: Optional[CalendarProvider] = None,
        notification_provider: Optional[NotificationProvider] = None,
        memory_service: Optional[Any] = None,
        browser_service: Optional[Any] = None,
        agent_service: Optional[Any] = None,
        voice_service: Optional[Any] = None,
    ) -> None:
        self.config = config or ContextAwarenessConfig()
        self.event_bus = event_bus
        self.health_manager = health_manager
        self.audit_logger = audit_logger or AuditLogger()
        self.tool_executor = tool_executor
        self.memory_service = memory_service
        self.browser_service = browser_service
        self.agent_service = agent_service
        self.voice_service = voice_service

        # Core guards and managers
        self.permission_guard = ContextPermissionGuard(self.config)
        self.privacy_guard = PrivacyGuard(self.config)
        self.deduplication_manager = DeduplicationManager()
        self.interruption_manager = InterruptionManager(self.config)
        self.relevance_engine = RelevanceEngine()
        self.trigger_engine = TriggerEngine()
        self.suggestion_generator = SuggestionGenerator(
            relevance_engine=self.relevance_engine,
            interruption_manager=self.interruption_manager,
            deduplication_manager=self.deduplication_manager,
        )
        self.proactive_dispatcher = (
            ProactiveActionDispatcher(tool_executor=self.tool_executor, audit_logger=self.audit_logger, event_bus=self.event_bus)
            if self.tool_executor
            else None
        )

        # Registry
        self.registry = ContextRegistry()

        # Providers
        self._calendar_provider = calendar_provider or MockCalendarProvider()
        self._notification_provider = notification_provider or MockNotificationProvider()
        self.registry.register_calendar_provider("default", self._calendar_provider)
        self.registry.register_notification_provider("default", self._notification_provider)

        # Instantiate Observers
        self.foreground_observer = ForegroundObserver(
            config=self.config,
            permission_guard=self.permission_guard,
            privacy_guard=self.privacy_guard,
            event_bus=self.event_bus,
            on_app_change=self._on_foreground_app_changed,
        )
        self.activity_observer = ActivityObserver(
            config=self.config,
            permission_guard=self.permission_guard,
            event_bus=self.event_bus,
            on_activity_change=self._on_user_activity_changed,
        )
        self.notification_observer = NotificationObserver(
            config=self.config,
            permission_guard=self.permission_guard,
            privacy_guard=self.privacy_guard,
            provider=self._notification_provider,
            event_bus=self.event_bus,
            on_notification=self._on_notification_received,
        )
        self.calendar_observer = CalendarObserver(
            config=self.config,
            permission_guard=self.permission_guard,
            privacy_guard=self.privacy_guard,
            provider=self._calendar_provider,
            event_bus=self.event_bus,
            on_event_approaching=self._on_calendar_event_approaching,
        )
        self.scheduler = ContextScheduler(
            config=self.config,
            permission_guard=self.permission_guard,
            event_bus=self.event_bus,
            on_schedule_reached=self._on_schedule_reached,
        )

        # Register observers
        self.registry.register_observer(self.foreground_observer)
        self.registry.register_observer(self.activity_observer)
        self.registry.register_observer(self.notification_observer)
        self.registry.register_observer(self.calendar_observer)
        self.registry.register_observer(self.scheduler)

        # Active tasks and context state
        self._active_task_context: Optional[TaskStateContext] = None
        self._recent_suggestions: List[ContextualSuggestion] = []
        self._is_running: bool = False

        # Register diagnostics with HealthManager
        self._register_health_checks()

    def set_active_task_context(self, task_id: str, task_name: str, status: str = "running") -> None:
        """Inform context service of the currently running BUDDY agent task."""
        self._active_task_context = TaskStateContext(
            task_id=task_id,
            task_name=task_name,
            status=status,
            deadline=None,
        )

    def clear_active_task_context(self) -> None:
        self._active_task_context = None

    def _register_health_checks(self) -> None:
        """Register all component diagnostics with HealthManager."""
        if not self.health_manager:
            return

        self.health_manager.register_check("ContextAwareness", self.health)
        self.health_manager.register_check("ForegroundObserver", self.foreground_observer.health)
        self.health_manager.register_check("ActivityObserver", self.activity_observer.health)
        self.health_manager.register_check("NotificationObserver", self.notification_observer.health)
        self.health_manager.register_check("CalendarProvider", self._calendar_provider.health)
        self.health_manager.register_check("Scheduler", self.scheduler.health)
        self.health_manager.register_check(
            "TriggerEngine",
            lambda: HealthCheckResult(
                name="TriggerEngine",
                status=HealthStatus.HEALTHY,
                message="Deterministic trigger engine operational",
            ),
        )
        self.health_manager.register_check(
            "ProactiveAssistant",
            lambda: HealthCheckResult(
                name="ProactiveAssistant",
                status=HealthStatus.HEALTHY if self.config.proactive_assistance_enabled else HealthStatus.DEGRADED,
                message="Proactive assistant enabled" if self.config.proactive_assistance_enabled else "Proactive assistant disabled",
            ),
        )

    async def start(self) -> None:
        """Start all enabled context observers."""
        if not self.config.context_awareness_enabled:
            logger.info("Context awareness is disabled by configuration.")
            return

        self._is_running = True
        logger.info("Starting Context Awareness Subsystem...")

        # Start individual observers
        await self.foreground_observer.start()
        await self.activity_observer.start()
        await self.notification_observer.start()
        await self.calendar_observer.start()
        await self.scheduler.start()

        self._audit("CONTEXT_OBSERVER_ENABLED", "all", "Subsystem initialized and started")

    async def stop(self) -> None:
        """Stop all context observers and clean up background tasks."""
        self._is_running = False
        logger.info("Stopping Context Awareness Subsystem...")

        await self.foreground_observer.stop()
        await self.activity_observer.stop()
        await self.notification_observer.stop()
        await self.calendar_observer.stop()
        await self.scheduler.stop()

        self._audit("CONTEXT_OBSERVER_DISABLED", "all", "Subsystem stopped")

    async def cancel(self) -> None:
        """Immediately cancel all observer tasks."""
        await self.stop()

    def get_current_snapshot(self) -> ContextSnapshot:
        """Capture and return the current privacy-filtered context snapshot."""
        # 1. Foreground application
        fg_info = self.foreground_observer.current_app

        # 2. Activity state
        act_state = self.activity_observer.current_state

        # 3. Browser context (from BrowserService if active)
        browser_info = None
        if self.browser_service and self.config.browser_context_enabled:
            try:
                # Loop 9 browser service safe metadata
                browser_info = BrowserContextInfo(
                    active_domain=getattr(self.browser_service, "active_domain", None),
                    page_category="web_browsing",
                    trust=TrustClassification.UNTRUSTED,
                )
            except Exception:
                pass

        snapshot = ContextSnapshot(
            foreground_app=fg_info,
            window_title=fg_info.window_title if fg_info else None,
            activity_state=act_state,
            active_buddy_task=self._active_task_context,
            browser_context=browser_info,
            sensitivity=SensitivityLevel.SAFE,
        )

        # Enforce privacy guard
        sanitized = self.privacy_guard.sanitize_snapshot(snapshot)

        if sanitized.sensitivity == SensitivityLevel.HIGHLY_SENSITIVE:
            self._audit(
                "CONTEXT_PRIVACY_FILTER_TRIGGERED",
                fg_info.process_name if fg_info else "unknown",
                "Sensitive context detected; redacted window title and suppressed assistance",
            )
            self._publish_sync(
                ContextPrivacyFilterTriggeredEvent(
                    app_name=fg_info.process_name if fg_info else "unknown",
                    classification=SensitivityLevel.HIGHLY_SENSITIVE,
                )
            )

        self._publish_sync(
            ContextSnapshotCreatedEvent(
                snapshot_id=sanitized.snapshot_id,
                activity_state=sanitized.activity_state.value,
                foreground_app=sanitized.foreground_app.process_name if sanitized.foreground_app else None,
                sensitivity=sanitized.sensitivity,
            )
        )

        return sanitized

    async def handle_trigger(self, trigger: ContextTrigger) -> List[ContextualSuggestion]:
        """Process an incoming trigger through evaluation, scoring, budget, and proposal."""
        if not self.config.context_awareness_enabled or not self.config.proactive_assistance_enabled:
            return []

        self._audit("CONTEXT_TRIGGER_DETECTED", trigger.source, f"Trigger fired: {trigger.trigger_type.value}")
        await self._publish(
            ContextTriggerDetectedEvent(
                trigger_id=trigger.trigger_id,
                trigger_type=trigger.trigger_type.value,
                source=trigger.source,
                trust=trigger.trust.value,
            )
        )

        snapshot = self.get_current_snapshot()

        # If context is sensitive, suppress proactive assistance
        if snapshot.sensitivity in (SensitivityLevel.SENSITIVE, SensitivityLevel.HIGHLY_SENSITIVE):
            logger.info("Trigger %s suppressed due to sensitive application context.", trigger.trigger_type.value)
            self._audit("PROACTIVE_SUGGESTION_SUPPRESSED", trigger.source, "Suppressed by sensitive context")
            return []

        # Check quiet hours
        if self.interruption_manager.is_in_quiet_hours():
            is_critical = trigger.payload.get("is_critical", False)
            if not is_critical:
                logger.info("Trigger %s suppressed due to active quiet hours.", trigger.trigger_type.value)
                self._audit("QUIET_HOURS_SUPPRESSION", trigger.source, "Suppressed by quiet hours")
                await self._publish(
                    QuietHoursSuppressionEvent(
                        trigger_id=trigger.trigger_id,
                        quiet_window=f"{self.config.quiet_hours_start} - {self.config.quiet_hours_end}",
                    )
                )
                return []

        # Evaluate through deterministic TriggerEngine
        candidates = self.trigger_engine.evaluate(trigger, snapshot)
        created_suggestions: List[ContextualSuggestion] = []

        for msg, base_policy, proposal in candidates:
            # Generate suggestion with relevance, cooldown, deduplication
            suggestion = self.suggestion_generator.create_suggestion(
                trigger=trigger,
                snapshot=snapshot,
                message=msg,
                base_policy_level=base_policy,
                proposal=proposal,
                is_critical=trigger.payload.get("is_critical", False),
            )

            if not suggestion:
                self._audit("PROACTIVE_SUGGESTION_SUPPRESSED", trigger.source, f"Suppressed: {msg[:30]}")
                await self._publish(
                    ProactiveSuggestionSuppressedEvent(
                        trigger_id=trigger.trigger_id,
                        reason="cooldown_or_budget",
                        fingerprint=trigger.trigger_type.value,
                    )
                )
                continue

            created_suggestions.append(suggestion)
            self._recent_suggestions.append(suggestion)
            if len(self._recent_suggestions) > 20:
                self._recent_suggestions.pop(0)

            self._audit("PROACTIVE_SUGGESTION_CREATED", trigger.source, f"[{suggestion.policy_level.value}] {msg}")
            await self._publish(
                ProactiveSuggestionCreatedEvent(
                    suggestion_id=suggestion.suggestion_id,
                    trigger_id=trigger.trigger_id,
                    policy_level=suggestion.policy_level,
                    relevance_score=suggestion.relevance_score,
                    message=suggestion.message,
                )
            )

            # If proposal requires confirmation
            if suggestion.action_proposal and suggestion.policy_level == ProactivePolicyLevel.CONFIRMATION_REQUIRED:
                self._audit("PROACTIVE_ACTION_REQUIRES_CONFIRMATION", suggestion.action_proposal.suggested_tool, "Confirmation required")
                await self._publish(
                    ProactiveActionRequiresConfirmationEvent(
                        proposal_id=suggestion.action_proposal.proposal_id,
                        tool_name=suggestion.action_proposal.suggested_tool,
                        prompt_message=suggestion.message,
                    )
                )

            # If safe and authorized low-risk action (risk <= LOW, requires_confirmation = False)
            if (
                suggestion.action_proposal
                and suggestion.action_proposal.risk_level <= ToolRiskLevel.LOW
                and not suggestion.action_proposal.requires_confirmation
                and not suggestion.action_proposal.requires_authentication
                and self.proactive_dispatcher
            ):
                try:
                    await self.proactive_dispatcher.execute_proposal(suggestion.action_proposal)
                except Exception as e:
                    logger.warning("Error executing safe proactive action: %s", e)

            # Voice announcement integration (if voice enabled and not quiet hours)
            if self.voice_service and hasattr(self.voice_service, "speak"):
                try:
                    # Sanitize message before TTS
                    if not self.privacy_guard.is_sensitive_context(window_title=suggestion.message):
                        asyncio.create_task(self.voice_service.speak(suggestion.message))
                except Exception:
                    pass

        return created_suggestions

    def _on_foreground_app_changed(self, info: ForegroundAppInfo, trigger_type: TriggerType) -> None:
        trigger = ContextTrigger(
            trigger_type=trigger_type,
            source="observer.foreground",
            payload={"process_name": info.process_name, "app_identity": info.app_identity},
            trust=TrustClassification.TRUSTED,
        )
        asyncio.create_task(self.handle_trigger(trigger))

    def _on_user_activity_changed(self, state: ActivityState, trigger_type: TriggerType) -> None:
        trigger = ContextTrigger(
            trigger_type=trigger_type,
            source="observer.activity",
            payload={"activity_state": state.value},
            trust=TrustClassification.TRUSTED,
        )
        asyncio.create_task(self.handle_trigger(trigger))

    def _on_notification_received(self, notif: NotificationMetadata, trigger_type: TriggerType) -> None:
        trigger = ContextTrigger(
            trigger_type=trigger_type,
            source="observer.notifications",
            payload={"notification": notif.model_dump()},
            trust=TrustClassification.UNTRUSTED,  # Untrusted external content
        )
        asyncio.create_task(self.handle_trigger(trigger))

    def _on_calendar_event_approaching(self, ev: CalendarEvent, trigger_type: TriggerType) -> None:
        trigger = ContextTrigger(
            trigger_type=trigger_type,
            source="observer.calendar",
            payload={"event": ev.model_dump(), "is_critical": ev.is_critical},
            trust=TrustClassification.UNTRUSTED,  # Untrusted external data
        )
        asyncio.create_task(self.handle_trigger(trigger))

    def _on_schedule_reached(self, item: ScheduledItem, trigger_type: TriggerType) -> None:
        trigger = ContextTrigger(
            trigger_type=trigger_type,
            source="observer.scheduler",
            payload={"item": item.model_dump(), "is_critical": item.is_critical},
            trust=TrustClassification.TRUSTED,
        )
        asyncio.create_task(self.handle_trigger(trigger))

    def get_ui_state(self) -> ContextAwarenessUIState:
        """Produce read-only view model for UI presentation."""
        snapshot = self.get_current_snapshot()
        obs_status = {
            obs.name: obs.status.value for obs in self.registry.list_observers()
        }

        recent = [
            {
                "id": s.suggestion_id,
                "message": s.message,
                "policy_level": s.policy_level.value,
                "relevance": s.relevance_score,
                "created_at": s.created_at,
            }
            for s in self._recent_suggestions[-5:]
        ]

        return ContextAwarenessUIState(
            context_awareness_enabled=self.config.context_awareness_enabled,
            proactive_assistance_enabled=self.config.proactive_assistance_enabled,
            foreground_app=snapshot.foreground_app.app_identity if snapshot.foreground_app else "None",
            activity_state=snapshot.activity_state.value,
            observers=obs_status,
            quiet_hours_active=self.interruption_manager.is_in_quiet_hours(),
            quiet_hours_schedule=f"{self.config.quiet_hours_start} -> {self.config.quiet_hours_end}",
            recent_suggestions=recent,
        )

    def health(self) -> HealthCheckResult:
        """Produce overall health status for ContextAwareness."""
        if not self.config.context_awareness_enabled:
            return HealthCheckResult(
                name="ContextAwareness",
                status=HealthStatus.HEALTHY,
                message="Context awareness is disabled by configuration",
                timestamp=time.time(),
            )

        # Check if any observers are degraded
        statuses = [obs.status for obs in self.registry.list_observers()]
        if any(s == ObserverStatus.FAILED for s in statuses):
            overall = HealthStatus.UNHEALTHY
        elif any(s == ObserverStatus.DEGRADED for s in statuses):
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        return HealthCheckResult(
            name="ContextAwareness",
            status=overall,
            message="Context awareness operational",
            timestamp=time.time(),
            details={"is_running": self._is_running},
        )

    def _audit(self, event_type: str, resource: str, details_msg: str) -> None:
        try:
            self.audit_logger.log_event(
                event_type=event_type,
                user="system.context",
                resource=resource,
                action="evaluate",
                status="SUCCESS",
                details={"message": details_msg},
            )
        except Exception:
            pass

    async def _publish(self, event: Any) -> None:
        if self.event_bus:
            try:
                await self.event_bus.publish(event)
            except Exception as e:
                logger.debug("Failed to publish event %s: %s", type(event).__name__, e)

    def _publish_sync(self, event: Any) -> None:
        if self.event_bus:
            try:
                self.event_bus.publish_sync(event)
            except Exception as e:
                logger.debug("Failed to publish_sync event %s: %s", type(event).__name__, e)
