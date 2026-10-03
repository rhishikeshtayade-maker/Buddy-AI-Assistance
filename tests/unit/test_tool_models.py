"""Unit tests for BUDDY Tool Models and validation contracts."""

from __future__ import annotations

import unittest
from pydantic import ValidationError

from app.tools.models import (
    ToolDefinition,
    ToolExecutionStatus,
    ToolPermissionLevel,
    ToolRequest,
    ToolResult,
    ToolRiskLevel,
)


class TestToolModels(unittest.TestCase):
    """Validate behavior and constraints of tool data models."""

    def test_tool_definition_valid(self) -> None:
        defn = ToolDefinition(
            name="test.tool",
            description="A test tool definition",
            input_schema={"type": "object"},
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.SESSION,
            requires_confirmation=False,
            requires_authentication=False,
            timeout_seconds=5.0,
        )
        self.assertEqual(defn.name, "test.tool")
        self.assertEqual(defn.risk_level, ToolRiskLevel.LOW)
        self.assertEqual(defn.permission_level, ToolPermissionLevel.SESSION)
        self.assertEqual(defn.timeout_seconds, 5.0)

    def test_tool_definition_rejects_empty_or_spaced_name(self) -> None:
        with self.assertRaises(ValidationError):
            ToolDefinition(name="invalid tool name", description="desc")
        with self.assertRaises(ValidationError):
            ToolDefinition(name="", description="desc")

    def test_tool_definition_is_immutable(self) -> None:
        defn = ToolDefinition(name="system.info", description="desc")
        with self.assertRaises(ValidationError):
            defn.name = "changed.name"  # type: ignore

    def test_tool_request_instantiation(self) -> None:
        req = ToolRequest(
            tool_name="app.open",
            arguments={"application": "notepad"},
            reason="User asked to write notes",
        )
        self.assertEqual(req.tool_name, "app.open")
        self.assertEqual(req.arguments["application"], "notepad")
        self.assertEqual(req.requested_by, "ai")
        self.assertTrue(len(req.request_id) > 0)

    def test_tool_result_verification_contract(self) -> None:
        res = ToolResult(
            request_id="req-123",
            tool_name="app.open",
            success=True,
            verified=True,
            status=ToolExecutionStatus.SUCCEEDED,
            output={"launched": True},
        )
        self.assertTrue(res.success)
        self.assertTrue(res.verified)
        self.assertEqual(res.status, ToolExecutionStatus.SUCCEEDED)


if __name__ == "__main__":
    unittest.main()
