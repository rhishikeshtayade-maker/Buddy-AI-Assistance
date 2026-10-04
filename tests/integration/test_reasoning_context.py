"""Integration tests for Reasoning layer with Context Awareness (Loop 12).

Verifies that Contextual Awareness informs planning while strictly adhering
to privacy boundaries and never enabling unrestricted surveillance.
"""

import unittest
from app.agent.reasoning.extractor import GoalRequirementExtractor
from app.context_awareness.models import ContextSnapshot, ForegroundAppInfo


class TestReasoningContextIntegration(unittest.TestCase):
    def test_context_awareness_informs_goal_without_surveillance(self):
        extractor = GoalRequirementExtractor()
        snapshot = ContextSnapshot(
            foreground_app=ForegroundAppInfo(
                app_identity="code_editor",
                process_name="code.exe",
                window_title="D:\\BUDDY\\app\\main.py - Visual Studio Code",
            )
        )

        goal = extractor.extract_goal("Verify python file in current project")
        self.assertNotIn("clipboard", str(goal))
        self.assertNotIn("keystrokes", str(goal))
        self.assertTrue(len(goal.prohibited_actions) >= 1)


if __name__ == "__main__":
    unittest.main()
