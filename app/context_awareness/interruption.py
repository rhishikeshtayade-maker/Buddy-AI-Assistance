"""BUDDY Interruption Management & Quiet Hours Subsystem.

Enforces user respect boundaries:
1. Quiet Hours: Silences proactive interruptions unless flagged critical.
2. Interruption Budget: Caps maximum suggestions per rolling hour window.
3. Cooldown: Prevents identical suggestions from firing within a cooldown period.
"""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, Optional

from app.context_awareness.config import ContextAwarenessConfig
from app.context_awareness.models import (
    InterruptionBudgetDecision,
    SensitivityLevel,
)
from app.core.logging import get_logger

logger = get_logger("context.interruption")


class InterruptionManager:
    """Evaluates quiet hours, cooldowns, and hourly interruption budgets."""

    def __init__(self, config: ContextAwarenessConfig) -> None:
        self.config = config
        self._interruption_history: Deque[float] = deque()
        self._cooldown_tracker: Dict[str, float] = {}

    def is_in_quiet_hours(self, current_dt: Optional[datetime] = None) -> bool:
        """Evaluate if the current local time falls within configured quiet hours."""
        if not self.config.quiet_hours_enabled:
            return False

        dt = current_dt or datetime.now()
        current_time_str = dt.strftime("%H:%M")

        start = self.config.quiet_hours_start
        end = self.config.quiet_hours_end

        if start <= end:
            # Daytime interval, e.g. 13:00 to 15:00
            return start <= current_time_str < end
        else:
            # Overnight interval, e.g. 22:00 to 07:00
            return current_time_str >= start or current_time_str < end

    def check_interruption_budget(
        self,
        fingerprint: str,
        is_critical: bool = False,
        sensitivity: SensitivityLevel = SensitivityLevel.SAFE,
        current_dt: Optional[datetime] = None,
    ) -> InterruptionBudgetDecision:
        """Determine if a proactive suggestion is allowed to interrupt the user."""
        now = time.time()

        # 1. Sensitive context suppression
        if sensitivity in (SensitivityLevel.SENSITIVE, SensitivityLevel.HIGHLY_SENSITIVE, SensitivityLevel.BLOCKED):
            return InterruptionBudgetDecision.SENSITIVE_CONTEXT_SUPPRESSED

        # 2. Quiet Hours check (critical reminders bypass quiet hours)
        if self.is_in_quiet_hours(current_dt) and not is_critical:
            return InterruptionBudgetDecision.QUIET_HOURS_SUPPRESSED

        # 3. Cooldown check (fingerprint cooldown)
        last_presented = self._cooldown_tracker.get(fingerprint)
        if last_presented and (now - last_presented < self.config.suggestion_cooldown_seconds):
            if not is_critical:
                return InterruptionBudgetDecision.COOLDOWN_SUPPRESSED

        # 4. Hourly budget check (prune records older than 1 hour / 3600s)
        self._prune_hourly_history(now)
        if len(self._interruption_history) >= self.config.max_interruptions_per_hour and not is_critical:
            return InterruptionBudgetDecision.HOURLY_LIMIT_EXCEEDED

        return InterruptionBudgetDecision.ALLOWED

    def record_interruption(self, fingerprint: str) -> None:
        """Record that an interruption occurred, consuming budget and resetting cooldown."""
        now = time.time()
        self._interruption_history.append(now)
        self._cooldown_tracker[fingerprint] = now

    def _prune_hourly_history(self, now: float) -> None:
        while self._interruption_history and (now - self._interruption_history[0] > 3600.0):
            self._interruption_history.popleft()

    def reset(self) -> None:
        """Reset budget and cooldown trackers."""
        self._interruption_history.clear()
        self._cooldown_tracker.clear()
