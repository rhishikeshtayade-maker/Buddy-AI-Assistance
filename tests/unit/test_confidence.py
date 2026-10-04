"""Unit tests for Confidence Evaluator (Loop 12)."""

import unittest
from app.agent.models import Task, TaskStep
from app.agent.reasoning.confidence import ConfidenceEvaluator
from app.agent.reasoning.models import ConfidenceLevel, Goal


class TestConfidenceEvaluator(unittest.TestCase):
    def setUp(self):
        self.evaluator = ConfidenceEvaluator()

    def test_goal_confidence_clear_vs_ambiguous(self):
        clear_goal = Goal(objective="Read user instructions")
        conf_clear = self.evaluator.evaluate_goal_confidence(clear_goal)
        self.assertGreaterEqual(conf_clear.score, 0.5)

    def test_plan_confidence_empty_vs_verified(self):
        empty_task = Task(user_goal="Empty", steps=[])
        conf_empty = self.evaluator.evaluate_plan_confidence(empty_task)
        self.assertEqual(conf_empty.score, 0.0)

        step = TaskStep(
            description="Verified action",
            tool_name="file.read",
            expected_result="File exists",
            verification_policy="empirical",
        )
        task = Task(user_goal="Verified", steps=[step])
        conf_verified = self.evaluator.evaluate_plan_confidence(task)
        self.assertGreater(conf_verified.score, 0.7)

    def test_step_execution_confidence(self):
        step = TaskStep(description="Action", tool_name="system.info")
        conf_succ = self.evaluator.evaluate_step_execution(step, success=True, verified=True)
        self.assertEqual(conf_succ.level, ConfidenceLevel.VERY_HIGH)

        conf_fail = self.evaluator.evaluate_step_execution(step, success=False, verified=False)
        self.assertEqual(conf_fail.level, ConfidenceLevel.VERY_LOW)


if __name__ == "__main__":
    unittest.main()
