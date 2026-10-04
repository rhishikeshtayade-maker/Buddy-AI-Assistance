"""BUDDY Contextual Suggestion Generator.

Transforms validated triggers, relevance scores, and proposals into typed ContextualSuggestions.
Enforces that dangerous actions are never classified as automatic.
"""

from __future__ import annotations

import time
import uuid
from typing import List, Optional

from app.context_awareness.deduplication import DeduplicationManager
from app.context_awareness.interruption import InterruptionManager
from app.context_awareness.models import (
    ContextSnapshot,
    ContextTrigger,
    ContextualSuggestion,
    InterruptionBudgetDecision,
    ProactiveActionProposal,
    ProactivePolicyLevel,
    SensitivityLevel,
)
from app.context_awareness.relevance import RelevanceEngine
from app.core.logging import get_logger
from app.tools.models import ToolRiskLevel

logger = get_logger("context.suggestions")


class SuggestionGenerator:
    """Coordinates relevance scoring, deduplication, and policy level determination for suggestions."""

    def __init__(
        self,
        relevance_engine: RelevanceEngine,
        interruption_manager: InterruptionManager,
        deduplication_manager: DeduplicationManager,
    ) -> None:
        self.relevance_engine = relevance_engine
        self.interruption_manager = interruption_manager
        self.deduplication_manager = deduplication_manager

    def create_suggestion(
        self,
        trigger: ContextTrigger,
        snapshot: ContextSnapshot,
        message: str,
        base_policy_level: ProactivePolicyLevel,
        proposal: Optional[ProactiveActionProposal] = None,
        is_critical: bool = False,
    ) -> Optional[ContextualSuggestion]:
        """Produce a filtered, deduplicated ContextualSuggestion or None if suppressed."""
        # 1. Calculate relevance score
        score = self.relevance_engine.calculate_score(trigger, snapshot)
        if score < self.relevance_engine.min_relevance_threshold and not is_critical:
            logger.debug("Suggestion rejected: relevance score %.2f below threshold", score)
            return None

        # 2. Determine and enforce policy tier
        policy_level = base_policy_level
        if proposal:
            # Enforce hard security bounds on proactive proposals
            if proposal.risk_level >= ToolRiskLevel.HIGH:
                # High/Critical risk actions NEVER auto-execute; must require authentication or confirmation
                if proposal.risk_level == ToolRiskLevel.CRITICAL:
                    policy_level = ProactivePolicyLevel.AUTH_REQUIRED
                    proposal.requires_authentication = True
                else:
                    policy_level = ProactivePolicyLevel.CONFIRMATION_REQUIRED
                    proposal.requires_confirmation = True
            elif proposal.risk_level >= ToolRiskLevel.MODERATE:
                policy_level = ProactivePolicyLevel.CONFIRMATION_REQUIRED
                proposal.requires_confirmation = True

        # 3. Compute fingerprint
        fingerprint = self.deduplication_manager.compute_suggestion_fingerprint(
            message=message,
            trigger_type=trigger.trigger_type,
            target_tool=proposal.suggested_tool if proposal else None,
        )

        # 4. Check interruption budget, quiet hours, cooldown, sensitivity
        decision = self.interruption_manager.check_interruption_budget(
            fingerprint=fingerprint,
            is_critical=is_critical,
            sensitivity=snapshot.sensitivity,
        )

        if decision != InterruptionBudgetDecision.ALLOWED:
            logger.info("Suggestion '%s' suppressed: %s", message[:40], decision.value)
            return None

        # 5. Check deduplication cache
        if self.deduplication_manager.is_duplicate(fingerprint) and not is_critical:
            logger.info("Suggestion '%s' suppressed by deduplication.", message[:40])
            return None

        # Record seen
        self.deduplication_manager.record_seen(fingerprint)
        self.interruption_manager.record_interruption(fingerprint)

        suggestion = ContextualSuggestion(
            suggestion_id=str(uuid.uuid4()),
            trigger_id=trigger.trigger_id,
            message=message,
            relevance_score=score,
            policy_level=policy_level,
            action_proposal=proposal,
            created_at=time.time(),
            expires_at=time.time() + 600.0,
            fingerprint=fingerprint,
        )
        logger.info("Created contextual suggestion: [%s] %s", policy_level.value, message)
        return suggestion
