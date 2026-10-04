"""BUDDY Contextual Relevance Engine.

Computes deterministic relevance scores (0.0 to 1.0) without requiring an LLM.
Ensures fast, predictable, testable, and privacy-preserving proactive decision-making.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from app.context_awareness.models import (
    ActivityState,
    ContextSnapshot,
    ContextTrigger,
    TriggerType,
)

BASE_TRIGGER_WEIGHTS: Dict[TriggerType, float] = {
    TriggerType.TaskDeadlineApproaching: 0.90,
    TriggerType.CalendarEventApproaching: 0.85,
    TriggerType.ScheduledTimeReached: 0.80,
    TriggerType.AppOpened: 0.70,
    TriggerType.AppFocused: 0.65,
    TriggerType.TaskCompleted: 0.60,
    TriggerType.TaskFailed: 0.75,
    TriggerType.BrowserContextChanged: 0.50,
    TriggerType.NotificationReceived: 0.45,
    TriggerType.UserBecameActive: 0.40,
    TriggerType.UserBecameIdle: 0.30,
    TriggerType.AppClosed: 0.20,
}


class RelevanceEngine:
    """Calculates deterministic relevance scores for contextual trigger events."""

    def __init__(self, min_relevance_threshold: float = 0.40) -> None:
        self.min_relevance_threshold = min_relevance_threshold

    def calculate_score(
        self,
        trigger: ContextTrigger,
        snapshot: ContextSnapshot,
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> float:
        """Calculate normalized relevance score in [0.0, 1.0]."""
        # 1. Base weight from trigger type
        base_weight = BASE_TRIGGER_WEIGHTS.get(trigger.trigger_type, 0.50)

        # 2. Activity adjustment
        activity_modifier = 0.0
        if snapshot.activity_state == ActivityState.ACTIVE:
            activity_modifier = +0.10
        elif snapshot.activity_state == ActivityState.IDLE:
            activity_modifier = -0.10
        elif snapshot.activity_state == ActivityState.AWAY:
            activity_modifier = -0.30

        # 3. Contextual synergy
        synergy_modifier = 0.0
        # If trigger is about an app and that app is currently focused
        if trigger.trigger_type in (TriggerType.AppOpened, TriggerType.AppFocused):
            if snapshot.foreground_app and snapshot.active_buddy_task:
                synergy_modifier = +0.15

        # If critical flag is set in payload
        if trigger.payload.get("is_critical") or (
            trigger.payload.get("event") and trigger.payload.get("event", {}).get("is_critical")
        ):
            synergy_modifier += 0.20

        # 4. User preference modifiers from memory or config
        pref_modifier = 0.0
        if user_preferences:
            pref_weight = user_preferences.get("relevance_weight_modifier", 0.0)
            pref_modifier += float(pref_weight)

        # Combine with confidence
        raw_score = (base_weight + activity_modifier + synergy_modifier + pref_modifier) * trigger.confidence

        # Clamp strictly between 0.0 and 1.0
        final_score = max(0.0, min(1.0, round(raw_score, 3)))
        return final_score

    def is_relevant(
        self,
        trigger: ContextTrigger,
        snapshot: ContextSnapshot,
        user_preferences: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Check if score meets or exceeds minimum threshold."""
        score = self.calculate_score(trigger, snapshot, user_preferences)
        return score >= self.min_relevance_threshold
