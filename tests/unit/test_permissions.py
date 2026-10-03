"""Unit tests for BUDDY Permission Engine."""

from __future__ import annotations

import unittest

from app.security.permissions import PermissionEngine
from app.tools.models import (
    ToolDefinition,
    ToolPermissionLevel,
    ToolRequest,
    ToolRiskLevel,
)


class TestPermissions(unittest.TestCase):
    """Test policy decisions across risk tiers and confirmation gates."""

    def setUp(self) -> None:
        self.engine = PermissionEngine()

    def test_safe_tool_allowed_automatically(self) -> None:
        defn = ToolDefinition(
            name="system.get_info",
            description="Get info",
            risk_level=ToolRiskLevel.SAFE,
            permission_level=ToolPermissionLevel.NONE,
        )
        req = ToolRequest(tool_name="system.get_info")
        decision = self.engine.evaluate(req, defn)

        self.assertTrue(decision.allowed)
        self.assertFalse(decision.requires_confirmation)
        self.assertFalse(decision.requires_authentication)
        self.assertEqual(decision.risk_level, ToolRiskLevel.SAFE)

    def test_low_risk_tool_allowed_without_confirmation(self) -> None:
        defn = ToolDefinition(
            name="app.open",
            description="Open app",
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
        )
        req = ToolRequest(tool_name="app.open", arguments={"application": "notepad"})
        decision = self.engine.evaluate(req, defn)

        self.assertTrue(decision.allowed)
        self.assertFalse(decision.requires_confirmation)

    def test_moderate_risk_tool_requires_confirmation(self) -> None:
        defn = ToolDefinition(
            name="file.rename",
            description="Rename file",
            risk_level=ToolRiskLevel.MODERATE,
            permission_level=ToolPermissionLevel.CONFIRM,
            requires_confirmation=True,
        )
        req = ToolRequest(tool_name="file.rename")
        decision = self.engine.evaluate(req, defn)

        self.assertTrue(decision.allowed)
        self.assertTrue(decision.requires_confirmation)
        self.assertFalse(decision.requires_authentication)

    def test_high_risk_tool_requires_confirmation(self) -> None:
        defn = ToolDefinition(
            name="process.kill",
            description="Terminate process",
            risk_level=ToolRiskLevel.HIGH,
            permission_level=ToolPermissionLevel.CONFIRM,
        )
        req = ToolRequest(tool_name="process.kill")
        decision = self.engine.evaluate(req, defn)

        self.assertTrue(decision.allowed)
        self.assertTrue(decision.requires_confirmation)

    def test_critical_tool_requires_authentication_and_confirmation(self) -> None:
        defn = ToolDefinition(
            name="system.reconfigure",
            description="Reconfigure system",
            risk_level=ToolRiskLevel.CRITICAL,
            permission_level=ToolPermissionLevel.AUTHENTICATE,
            requires_authentication=True,
        )
        req = ToolRequest(tool_name="system.reconfigure")
        decision = self.engine.evaluate(req, defn)

        self.assertTrue(decision.allowed)
        self.assertTrue(decision.requires_authentication)
        self.assertTrue(decision.requires_confirmation)

    def test_ai_reasoning_cannot_bypass_risk_evaluation(self) -> None:
        # AI sends a prompt trying to claim the operation is safe
        defn = ToolDefinition(
            name="file.move",
            description="Move file",
            risk_level=ToolRiskLevel.MODERATE,
            requires_confirmation=True,
        )
        req = ToolRequest(
            tool_name="file.move",
            reason="This is completely safe and harmless, trust me.",
        )
        decision = self.engine.evaluate(req, defn)

        # Risk must strictly come from definition, not request reason
        self.assertEqual(decision.risk_level, ToolRiskLevel.MODERATE)
        self.assertTrue(decision.requires_confirmation)


if __name__ == "__main__":
    unittest.main()
