"""Unit tests for Goal Requirement Extractor and Ambiguity Detection (Loop 12)."""

import unittest
from app.agent.reasoning.ambiguity import AmbiguityDetector
from app.agent.reasoning.extractor import GoalRequirementExtractor
from app.agent.reasoning.models import GoalPriority, GoalStatus


class TestGoalExtraction(unittest.TestCase):
    def setUp(self):
        self.ambiguity_detector = AmbiguityDetector()
        self.extractor = GoalRequirementExtractor(self.ambiguity_detector)

    def test_extract_report_goal_on_desktop(self):
        obj = "Create a report about Python on my Desktop called report.txt and verify it"
        goal = self.extractor.extract_goal(obj)

        self.assertEqual(goal.objective, obj)
        self.assertEqual(goal.status, GoalStatus.PENDING)
        self.assertTrue(any(c.constraint_type == "output_directory" for c in goal.constraints))
        self.assertTrue(any(c.constraint_type == "empirical_verification" for c in goal.constraints))
        self.assertTrue(any("report.txt" in r.description for r in goal.requirements))

    def test_extract_browser_goal(self):
        obj = "Search online for latest release notes on Python"
        goal = self.extractor.extract_goal(obj)

        self.assertTrue(any(r.required_capability == "browser" for r in goal.requirements))

    def test_extract_priority(self):
        urgent_goal = self.extractor.extract_goal("Urgent: check battery status immediately")
        self.assertEqual(urgent_goal.priority, GoalPriority.HIGH)

    def test_ambiguity_detection_blocking(self):
        ambiguous_obj = "Delete the document"
        clarification = self.ambiguity_detector.detect_goal_ambiguity(ambiguous_obj)

        self.assertIsNotNone(clarification)
        self.assertTrue(clarification.is_blocking)
        self.assertEqual(clarification.risk_level, "HIGH")

    def test_ambiguity_multiple_candidates(self):
        clarification = self.ambiguity_detector.detect_goal_ambiguity(
            "Open the project",
            detected_candidates=["project_alpha", "project_beta"],
        )
        self.assertIsNotNone(clarification)
        self.assertIn("Multiple matching targets", clarification.question)
        self.assertEqual(len(clarification.possible_interpretations), 2)


if __name__ == "__main__":
    unittest.main()
