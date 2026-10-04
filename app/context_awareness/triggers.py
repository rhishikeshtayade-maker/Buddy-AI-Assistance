"""BUDDY Contextual Trigger Engine.

Evaluates incoming context triggers against environmental context and registered rules.
Produces ContextualSuggestion or ProactiveActionProposal.

CRITICAL SECURITY REQUIREMENT:
The trigger engine NEVER executes tools directly.
All proposed actions must enter ToolRegistry and ToolExecutor via standard security channels.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.context_awareness.models import (
    ActivityState,
    CalendarEvent,
    ContextSnapshot,
    ContextTrigger,
    ContextualSuggestion,
    ProactiveActionProposal,
    ProactivePolicyLevel,
    ScheduledItem,
    SensitivityLevel,
    TriggerType,
    TrustClassification,
)
from app.core.logging import get_logger
from app.tools.models import ToolRiskLevel

logger = get_logger("context.triggers")

TriggerRuleHandler = Callable[[ContextTrigger, ContextSnapshot], Optional[Tuple[str, ProactivePolicyLevel, Optional[ProactiveActionProposal]]]]


class TriggerEngine:
    """Deterministic rule-based trigger evaluator."""

    def __init__(self) -> None:
        self._rules: List[TriggerRuleHandler] = []
        self._register_default_rules()

    def register_rule(self, handler: TriggerRuleHandler) -> None:
        """Register a custom contextual trigger evaluation rule."""
        self._rules.append(handler)

    def _register_default_rules(self) -> None:
        """Register built-in deterministic rules."""
        self.register_rule(self._rule_calendar_event_approaching)
        self.register_rule(self._rule_coding_task_context)
        self.register_rule(self._rule_scheduled_reminder)
        self.register_rule(self._rule_user_idle_transition)
        self.register_rule(self._rule_notification_received)
        self.register_rule(self._rule_task_deadline_approaching)

    def evaluate(
        self,
        trigger: ContextTrigger,
        snapshot: ContextSnapshot,
    ) -> List[Tuple[str, ProactivePolicyLevel, Optional[ProactiveActionProposal]]]:
        """Evaluate trigger across all rules and return suggestion candidates."""
        candidates = []
        for rule in self._rules:
            try:
                result = rule(trigger, snapshot)
                if result:
                    candidates.append(result)
            except Exception as e:
                logger.warning("Error evaluating trigger rule: %s", e)
        return candidates

    @staticmethod
    def _rule_calendar_event_approaching(
        trigger: ContextTrigger,
        snapshot: ContextSnapshot,
    ) -> Optional[Tuple[str, ProactivePolicyLevel, Optional[ProactiveActionProposal]]]:
        """Rule: Calendar event starting soon -> passive/active suggestion."""
        if trigger.trigger_type != TriggerType.CalendarEventApproaching:
            return None

        event_dict = trigger.payload.get("event")
        if not event_dict:
            return None

        title = event_dict.get("title", "Upcoming Event")
        start_time = event_dict.get("start_time", 0.0)
        minutes_left = max(1, round((start_time - time.time()) / 60))

        msg = f"Your calendar event '{title}' starts in approximately {minutes_left} minutes."
        proposal = None

        # If meeting notes URL or location exists, offer a SAFE tool proposal (e.g. show reminder or open safe path)
        if event_dict.get("location"):
            loc = event_dict.get("location")
            # Propose safe action if location is local path or simple note
            proposal = ProactiveActionProposal(
                reason=f"Open meeting notes for '{title}'",
                triggering_context_id=trigger.trigger_id,
                suggested_tool="system.get_info",
                arguments={"category": "calendar_context"},
                risk_level=ToolRiskLevel.SAFE,
                expiration=time.time() + 600.0,
                requires_confirmation=False,
                requires_authentication=False,
            )

        return (msg, ProactivePolicyLevel.SUGGESTION if proposal else ProactivePolicyLevel.PASSIVE, proposal)

    @staticmethod
    def _rule_coding_task_context(
        trigger: ContextTrigger,
        snapshot: ContextSnapshot,
    ) -> Optional[Tuple[str, ProactivePolicyLevel, Optional[ProactiveActionProposal]]]:
        """Rule: VS Code focused and active coding task pending -> offer assistance."""
        if trigger.trigger_type not in (TriggerType.AppFocused, TriggerType.AppOpened):
            return None

        app = snapshot.foreground_app
        if not app:
            return None

        proc_lower = app.process_name.lower()
        if "code" in proc_lower or "pycharm" in proc_lower or "devenv" in proc_lower:
            task = snapshot.active_buddy_task
            if task and task.task_name:
                msg = f"You are back in {app.app_identity}. Would you like to resume your pending task '{task.task_name}'?"
                return (msg, ProactivePolicyLevel.SUGGESTION, None)

        return None

    @staticmethod
    def _rule_scheduled_reminder(
        trigger: ContextTrigger,
        snapshot: ContextSnapshot,
    ) -> Optional[Tuple[str, ProactivePolicyLevel, Optional[ProactiveActionProposal]]]:
        """Rule: Scheduled time reached -> present reminder."""
        if trigger.trigger_type != TriggerType.ScheduledTimeReached:
            return None

        item_dict = trigger.payload.get("item", {})
        name = item_dict.get("name", "Reminder")
        msg = f"Scheduled reminder: {name}"

        # If item has a tool action request, propose it through normal policy
        proposal = None
        action_tool = item_dict.get("payload", {}).get("tool")
        if action_tool:
            tool_args = item_dict.get("payload", {}).get("arguments", {})
            proposal = ProactiveActionProposal(
                reason=f"Execute scheduled action for '{name}'",
                triggering_context_id=trigger.trigger_id,
                suggested_tool=action_tool,
                arguments=tool_args,
                risk_level=ToolRiskLevel.LOW,
                expiration=time.time() + 300.0,
                requires_confirmation=True,  # Scheduled actions require user confirmation by default
                requires_authentication=False,
            )

        return (msg, ProactivePolicyLevel.CONFIRMATION_REQUIRED if proposal else ProactivePolicyLevel.PASSIVE, proposal)

    @staticmethod
    def _rule_user_idle_transition(
        trigger: ContextTrigger,
        snapshot: ContextSnapshot,
    ) -> Optional[Tuple[str, ProactivePolicyLevel, Optional[ProactiveActionProposal]]]:
        """Rule: User became idle -> log or adjust proactive budget."""
        if trigger.trigger_type == TriggerType.UserBecameIdle:
            msg = "User became idle; pausing proactive interruptions."
            return (msg, ProactivePolicyLevel.PASSIVE, None)
        return None

    @staticmethod
    def _rule_notification_received(
        trigger: ContextTrigger,
        snapshot: ContextSnapshot,
    ) -> Optional[Tuple[str, ProactivePolicyLevel, Optional[ProactiveActionProposal]]]:
        """Rule: Notification received -> summarize if safe, never execute untrusted contents."""
        if trigger.trigger_type != TriggerType.NotificationReceived:
            return None

        notif = trigger.payload.get("notification", {})
        app = notif.get("source_app", "System")
        title = notif.get("title", "")
        preview = notif.get("preview", "")

        msg = f"Notification from {app}: {title}"
        if preview:
            msg += f" — {preview}"

        # Notifications NEVER generate automated action proposals (strict untrusted boundary)
        return (msg, ProactivePolicyLevel.PASSIVE, None)

    @staticmethod
    def _rule_task_deadline_approaching(
        trigger: ContextTrigger,
        snapshot: ContextSnapshot,
    ) -> Optional[Tuple[str, ProactivePolicyLevel, Optional[ProactiveActionProposal]]]:
        """Rule: Active BUDDY task deadline approaching."""
        if trigger.trigger_type != TriggerType.TaskDeadlineApproaching:
            return None

        task_name = trigger.payload.get("task_name", "Active Task")
        msg = f"Task deadline approaching for: '{task_name}'."
        return (msg, ProactivePolicyLevel.SUGGESTION, None)
