"""Unit tests for Task Budget enforcement (Loop 12)."""

import time
import unittest
from app.agent.reasoning.models import TaskBudget


class TestTaskBudget(unittest.TestCase):
    def test_step_budget_exhaustion(self):
        budget = TaskBudget(max_total_steps=3)
        budget.start()
        budget.record_step()
        budget.record_step()
        self.assertFalse(budget.is_exhausted()[0])

        budget.record_step()
        exhausted, reason = budget.is_exhausted()
        self.assertTrue(exhausted)
        self.assertIn("Max total steps", reason)

    def test_replan_budget_exhaustion(self):
        budget = TaskBudget(max_replans=2)
        budget.start()
        budget.record_replan()
        budget.record_replan()
        exhausted, reason = budget.is_exhausted()
        self.assertTrue(exhausted)
        self.assertIn("Max replans", reason)

    def test_time_budget_exhaustion(self):
        budget = TaskBudget(max_execution_time_seconds=0.01)
        budget.start()
        time.sleep(0.02)
        exhausted, reason = budget.is_exhausted()
        self.assertTrue(exhausted)
        self.assertIn("Max execution time", reason)


if __name__ == "__main__":
    unittest.main()
