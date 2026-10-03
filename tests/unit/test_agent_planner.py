"""Unit tests for BUDDY Agent TaskPlanner."""

from __future__ import annotations

import unittest

from app.agent.planner import TaskPlanner
from app.agent.validator import PlanValidationError, TaskPlanValidator
from app.ai.provider import MockAIProvider
from app.core.events import EventBus
from app.tools.builtin import register_builtin_tools
from app.tools.registry import ToolRegistry


class TestAgentPlanner(unittest.IsolatedAsyncioTestCase):
    """Test natural language goal decomposition into structured Task plans."""

    async def asyncSetUp(self) -> None:
        self.registry = ToolRegistry()
        register_builtin_tools(self.registry)
        self.event_bus = EventBus()
        self.mock_ai = MockAIProvider()
        self.validator = TaskPlanValidator(self.registry)
        self.planner = TaskPlanner(
            registry=self.registry,
            ai_provider=self.mock_ai,
            validator=self.validator,
            event_bus=self.event_bus,
        )

    async def asyncTearDown(self) -> None:
        await self.event_bus.shutdown()

    async def test_deterministic_plan_for_notepad_typing(self) -> None:
        """Deterministic plan: Open Notepad, type BUDDY TEST, finish."""
        task = await self.planner.plan("Open Notepad, type BUDDY TEST, and finish.")
        self.assertEqual(len(task.steps), 3)

        self.assertEqual(task.steps[0].tool_name, "app.open")
        self.assertEqual(task.steps[0].arguments["application"], "notepad")

        self.assertEqual(task.steps[1].tool_name, "mouse.click")
        self.assertEqual(task.steps[1].dependencies, ["step_open_notepad"])

        self.assertEqual(task.steps[2].tool_name, "keyboard.type_text")
        self.assertEqual(task.steps[2].arguments["text"], "BUDDY TEST")
        self.assertEqual(task.steps[2].dependencies, ["step_focus_editor"])

    async def test_ai_provider_structured_plan_generation(self) -> None:
        """Planner invokes AI provider and parses structured JSON output."""
        ai_plan_json = """{
          "steps": [
            {
              "step_id": "step_info",
              "description": "Query system diagnostic info",
              "tool_name": "system.get_info",
              "arguments": {},
              "dependencies": []
            },
            {
              "step_id": "step_battery",
              "description": "Query battery status",
              "tool_name": "system.get_battery",
              "arguments": {},
              "dependencies": ["step_info"]
            }
          ]
        }"""
        self.mock_ai.set_next_response(ai_plan_json)

        task = await self.planner.plan("Perform system diagnostics check.")
        self.assertEqual(len(task.steps), 2)
        self.assertEqual(task.steps[0].tool_name, "system.get_info")
        self.assertEqual(task.steps[1].tool_name, "system.get_battery")
        self.assertEqual(task.steps[1].dependencies, ["step_info"])

    async def test_planner_rejects_malformed_json_from_ai(self) -> None:
        """Malformed or non-JSON AI response raises PlanValidationError."""
        self.mock_ai.set_next_response("Sorry, I cannot plan this in JSON format: open notepad.")

        with self.assertRaises(PlanValidationError):
            await self.planner.plan("Some complex unparsable goal.")

    async def test_planner_does_not_execute_any_action(self) -> None:
        """The planner only produces a Task object; zero tools are executed."""
        task = await self.planner.plan("Open Notepad, type Hello, and finish.")
        self.assertIsNotNone(task)
        # All steps remain PENDING
        for step in task.steps:
            self.assertEqual(step.status.value, "PENDING")
            self.assertIsNone(step.result)


if __name__ == "__main__":
    unittest.main()
