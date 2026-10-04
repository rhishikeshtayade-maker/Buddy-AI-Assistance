"""BUDDY Explainable Confidence Model (Loop 12).

Calculates bounded confidence scores (0.0 to 1.0) and explainable reason codes.
CRITICAL INVARIANT: Confidence NEVER overrides security policy or confirmation gates.
"""

from __future__ import annotations

from typing import List, Optional

from app.agent.models import Task, TaskStep
from app.agent.reasoning.models import (
    ConfidenceAssessment,
    ConfidenceLevel,
    Goal,
)
from app.tools.models import ToolRiskLevel


class ConfidenceEvaluator:
    """Evaluates planning and execution confidence deterministically."""

    def evaluate_goal_confidence(self, goal: Goal) -> ConfidenceAssessment:
        """Score confidence for an extracted Goal based on requirements and ambiguity."""
        score = 0.85
        reason_codes: List[str] = []

        if goal.pending_clarification and goal.pending_clarification.is_blocking:
            score -= 0.55
            reason_codes.append("BLOCKING_AMBIGUITY_PRESENT")
        elif not goal.requirements:
            score -= 0.30
            reason_codes.append("NO_EXPLICIT_REQUIREMENTS_FOUND")
        else:
            reason_codes.append("STRUCTURED_REQUIREMENTS_PARSED")

        if any(c.strict for c in goal.constraints):
            reason_codes.append("STRICT_CONSTRAINTS_DEFINED")

        return ConfidenceAssessment.from_score(
            score=score,
            reason_codes=reason_codes,
            decision_category="goal_formulation",
        )

    def evaluate_plan_confidence(self, task: Task, goal: Optional[Goal] = None) -> ConfidenceAssessment:
        """Score confidence for a generated plan."""
        score = 0.90
        reason_codes: List[str] = []

        if not task.steps:
            return ConfidenceAssessment.from_score(
                0.0, ["EMPTY_PLAN"], decision_category="plan_validation"
            )

        # 1. Verification coverage
        verifiable_steps = [s for s in task.steps if s.verification_policy or s.expected_result]
        ratio = len(verifiable_steps) / len(task.steps)
        if ratio < 0.5:
            score -= 0.25
            reason_codes.append("LOW_VERIFICATION_COVERAGE")
        else:
            reason_codes.append("ADEQUATE_VERIFICATION_COVERAGE")

        # 2. High risk steps present
        has_high_risk = any(s.risk_level in (ToolRiskLevel.HIGH, ToolRiskLevel.CRITICAL) for s in task.steps)
        if has_high_risk:
            score -= 0.15
            reason_codes.append("CONTAINS_HIGH_RISK_ACTIONS")

        # 3. Step length
        if len(task.steps) > 10:
            score -= 0.10
            reason_codes.append("LONG_HORIZON_PLAN_DEPTH")
        else:
            reason_codes.append("COMPACT_PLAN_DEPTH")

        return ConfidenceAssessment.from_score(
            score=score,
            reason_codes=reason_codes,
            decision_category="plan_validation",
        )

    def evaluate_step_execution(
        self,
        step: TaskStep,
        success: bool,
        verified: bool,
    ) -> ConfidenceAssessment:
        """Score confidence after a step execution and empirical verification."""
        if not success:
            return ConfidenceAssessment.from_score(
                0.1, ["EXECUTION_FAILED"], decision_category="step_execution", verification_result=False
            )

        if not verified:
            return ConfidenceAssessment.from_score(
                0.4, ["UNVERIFIED_EXECUTION_OUTCOME"], decision_category="step_execution", verification_result=False
            )

        return ConfidenceAssessment.from_score(
            0.95, ["EMPIRICALLY_VERIFIED_SUCCESS"], decision_category="step_execution", verification_result=True
        )
