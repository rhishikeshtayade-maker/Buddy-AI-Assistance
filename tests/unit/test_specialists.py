"""Unit tests for Specialist Roles (Loop 12)."""

import unittest
from app.agent.models import TaskStep
from app.agent.specialists import (
    BrowserRole,
    CoderRole,
    ComputerRole,
    ResearcherRole,
    VerifierRole,
)


class TestSpecialists(unittest.TestCase):
    def test_researcher_boundary(self):
        researcher = ResearcherRole()
        self.assertTrue(researcher.is_tool_allowed("file.read"))
        self.assertTrue(researcher.is_tool_allowed("file.search"))
        self.assertFalse(researcher.is_tool_allowed("file.create"))

        steps = researcher.propose_steps("Find python papers")
        self.assertEqual(len(steps), 1)
        self.assertTrue(researcher.validate_proposed_step(steps[0]))

    def test_coder_boundary(self):
        coder = CoderRole()
        self.assertTrue(coder.is_tool_allowed("file.create"))
        self.assertFalse(coder.is_tool_allowed("browser.click"))

        steps = coder.propose_steps("Write utility script", context={"path": "util.py"})
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].tool_name, "file.create")

    def test_browser_boundary(self):
        browser = BrowserRole()
        self.assertTrue(browser.is_tool_allowed("browser.navigate"))
        self.assertFalse(browser.is_tool_allowed("file.create"))

    def test_computer_boundary(self):
        computer = ComputerRole()
        self.assertTrue(computer.is_tool_allowed("system.info"))
        self.assertFalse(browser_role := computer.is_tool_allowed("browser.navigate"))

    def test_verifier_strict_boundary(self):
        verifier = VerifierRole()
        self.assertTrue(verifier.is_tool_allowed("file.read"))
        self.assertFalse(verifier.is_tool_allowed("file.create"))
        steps = verifier.propose_steps("Check result", context={"file_path": "verified.txt"})
        self.assertEqual(steps[0].tool_name, "file.read")


if __name__ == "__main__":
    unittest.main()
