"""Unit tests for BUDDY Tool Registry."""

from __future__ import annotations

import unittest
from typing import Any, Dict

from app.core.exceptions import RegistryError
from app.tools.base import Tool
from app.tools.models import ToolDefinition, ToolRiskLevel
from app.tools.registry import ToolRegistry


class DummyTool(Tool):
    """Simple test tool."""

    def __init__(self, name: str = "dummy.tool") -> None:
        self._name = name

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self._name,
            description="Dummy test tool",
            risk_level=ToolRiskLevel.SAFE,
        )

    async def execute(self, arguments: Dict[str, Any]) -> Any:
        return {"result": "ok"}

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return True


class TestToolRegistry(unittest.TestCase):
    """Test ToolRegistry lifecycle and duplicate prevention."""

    def setUp(self) -> None:
        self.registry = ToolRegistry()

    def test_register_and_get_tool(self) -> None:
        tool = DummyTool()
        self.registry.register_tool(tool)

        self.assertTrue(self.registry.has_tool("dummy.tool"))
        retrieved = self.registry.get_tool("dummy.tool")
        self.assertIs(retrieved, tool)

    def test_duplicate_registration_rejected(self) -> None:
        tool1 = DummyTool("my.tool")
        tool2 = DummyTool("my.tool")
        self.registry.register_tool(tool1)

        with self.assertRaises(RegistryError):
            self.registry.register_tool(tool2)

    def test_invalid_tool_type_rejected(self) -> None:
        with self.assertRaises(RegistryError):
            self.registry.register_tool("not_a_tool")  # type: ignore

    def test_unregister_tool(self) -> None:
        tool = DummyTool("temp.tool")
        self.registry.register_tool(tool)
        self.assertTrue(self.registry.has_tool("temp.tool"))

        removed = self.registry.unregister_tool("temp.tool")
        self.assertTrue(removed)
        self.assertFalse(self.registry.has_tool("temp.tool"))
        self.assertIsNone(self.registry.get_tool("temp.tool"))

    def test_list_tools(self) -> None:
        self.registry.register_tool(DummyTool("tool.b"))
        self.registry.register_tool(DummyTool("tool.a"))

        definitions = self.registry.list_tools()
        self.assertEqual(len(definitions), 2)
        # Deterministic alphabetical ordering
        self.assertEqual(definitions[0].name, "tool.a")
        self.assertEqual(definitions[1].name, "tool.b")


if __name__ == "__main__":
    unittest.main()
