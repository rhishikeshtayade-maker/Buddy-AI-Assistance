"""Unit tests for BUDDY Reasoning Models (Loop 12)."""

import unittest
from app.agent.reasoning.models import (
    AutonomyLevel,
    Checkpoint,
    ClarificationRequest,
    ConfidenceAssessment,
    ConfidenceLevel,
    FailureDiagnosis,
    Goal,
    GoalAssumption,
    GoalConstraint,
    GoalPriority,
    GoalRequirement,
    GoalStatus,
    Milestone,
    ReasoningFailureCategory,
    StepEvaluationCategory,
    StepEvaluationResult,
    SubGoal,
    TaskBudget,
)


class TestReasoningModels(unittest.TestCase):
    def test_goal_creation_and_bounds(self):
        goal = Goal(
            objective="Organize research papers into archive directory",
            priority=GoalPriority.HIGH,
            autonomy_level=AutonomyLevel.SUPERVISED,
        )
        self.assertEqual(goal.status, GoalStatus.PENDING)
        self.assertEqual(goal.priority, GoalPriority.HIGH)
        self.assertTrue(goal.goal_id.startswith("goal_"))

    def test_checkpoint_sanitization(self):
        # Safe snapshot succeeds
        chk = Checkpoint(
            completed_step_ids=["step_1"],
            state_snapshot={"phase": "cleanup", "items_processed": 5},
        )
        self.assertEqual(chk.state_snapshot["items_processed"], 5)

        # Snapshot containing password / secret raises ValueError
        with self.assertRaises(ValueError):
            Checkpoint(
                completed_step_ids=["step_1"],
                state_snapshot={"api_key": "sk-12345"},
            )

        with self.assertRaises(ValueError):
            Checkpoint(
                completed_step_ids=["step_1"],
                state_snapshot={"user_password": "secret"},
            )

    def test_task_budget_limits(self):
        budget = TaskBudget(max_total_steps=5, max_replans=2, max_retries_per_step=1)
        budget.start()
        self.assertFalse(budget.is_exhausted()[0])

        for _ in range(5):
            budget.record_step()
        exhausted, reason = budget.is_exhausted()
        self.assertTrue(exhausted)
        self.assertIn("Max total steps", reason)

        # Retry limits
        self.assertTrue(budget.record_retry("step_1"))
        self.assertFalse(budget.record_retry("step_1"))

    def test_confidence_assessment_scoring(self):
        conf_vh = ConfidenceAssessment.from_score(0.95, ["high_evidence"])
        self.assertEqual(conf_vh.level, ConfidenceLevel.VERY_HIGH)

        conf_med = ConfidenceAssessment.from_score(0.50, ["partial_evidence"])
        self.assertEqual(conf_med.level, ConfidenceLevel.MEDIUM)

        conf_low = ConfidenceAssessment.from_score(0.10, ["weak_evidence"])
        self.assertEqual(conf_low.level, ConfidenceLevel.VERY_LOW)

    def test_clarification_request_model(self):
        req = ClarificationRequest(
            question="Which browser tab should be closed?",
            affected_requirement="tab_target",
            possible_interpretations=["Tab 1: GitHub", "Tab 2: Docs"],
            is_blocking=True,
        )
        self.assertTrue(req.is_blocking)
        self.assertFalse(req.answered)


if __name__ == "__main__":
    unittest.main()
