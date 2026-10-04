"""Unit tests for Milestone and Checkpoint Management (Loop 12)."""

import unittest
from app.agent.reasoning.milestones import MilestoneManager
from app.agent.reasoning.models import Goal, GoalStatus


class TestMilestones(unittest.TestCase):
    def setUp(self):
        self.manager = MilestoneManager()

    def test_milestone_initialization(self):
        goal = Goal(objective="Multi-phase research and report")
        milestones = self.manager.initialize_milestones_from_goal(goal)
        self.assertEqual(len(milestones), 3)
        self.assertEqual(milestones[0].title, "Preparation & Discovery")

    def test_milestone_update_and_checkpoint(self):
        goal = Goal(objective="Task with milestones")
        self.manager.initialize_milestones_from_goal(goal)

        checkpoint = self.manager.update_milestone_progress(
            goal=goal,
            completed_step_id="step_alpha",
            step_verified=True,
        )
        self.assertIsNotNone(checkpoint)
        self.assertIn("step_alpha", checkpoint.completed_step_ids)
        self.assertEqual(len(goal.checkpoints), 1)
        self.assertEqual(goal.milestones[0].status, GoalStatus.COMPLETED)


if __name__ == "__main__":
    unittest.main()
