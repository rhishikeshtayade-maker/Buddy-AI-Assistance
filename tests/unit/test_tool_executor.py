"""Unit tests for BUDDY ToolExecutor."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any, Dict

from app.core.events import EventBus
from app.security.authentication import MockAuthenticator
from app.security.confirmation import ConfirmationManager
from app.security.permissions import PermissionEngine
from app.tools.base import Tool
from app.tools.executor import ToolExecutor
from app.tools.models import (
    ToolDefinition,
    ToolExecutionStatus,
    ToolPermissionLevel,
    ToolRequest,
    ToolRiskLevel,
)
from app.tools.registry import ToolRegistry


class FastTool(Tool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="test.fast",
            description="Fast test tool",
            risk_level=ToolRiskLevel.SAFE,
            timeout_seconds=2.0,
        )

    async def execute(self, arguments: Dict[str, Any]) -> Any:
        return {"data": "done"}

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return raw_output == {"data": "done"}


class SlowTool(Tool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="test.slow",
            description="Slow timing-out tool",
            risk_level=ToolRiskLevel.SAFE,
            timeout_seconds=0.1,
        )

    async def execute(self, arguments: Dict[str, Any]) -> Any:
        await asyncio.sleep(0.5)
        return "too late"

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return True


class UnverifiedTool(Tool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="test.unverified",
            description="Tool that always fails verification",
            risk_level=ToolRiskLevel.SAFE,
        )

    async def execute(self, arguments: Dict[str, Any]) -> Any:
        return "executed"

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return False  # Intentionally failing verification


class ModerateConfirmTool(Tool):
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="test.confirm",
            description="Tool requiring confirmation",
            risk_level=ToolRiskLevel.MODERATE,
            permission_level=ToolPermissionLevel.CONFIRM,
            requires_confirmation=True,
        )

    async def execute(self, arguments: Dict[str, Any]) -> Any:
        return "confirmed execution"

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return True


class TestToolExecutor(unittest.IsolatedAsyncioTestCase):
    """Test ToolExecutor execution lifecycle, timeout, confirmation, and verification."""

    async def asyncSetUp(self) -> None:
        self.registry = ToolRegistry()
        self.registry.register_tool(FastTool())
        self.registry.register_tool(SlowTool())
        self.registry.register_tool(UnverifiedTool())
        self.registry.register_tool(ModerateConfirmTool())

        self.event_bus = EventBus()
        self.perm_engine = PermissionEngine()
        self.conf_mgr = ConfirmationManager()
        self.auth = MockAuthenticator(should_succeed=True)

        self.executor = ToolExecutor(
            registry=self.registry,
            permission_engine=self.perm_engine,
            confirmation_manager=self.conf_mgr,
            authenticator=self.auth,
            event_bus=self.event_bus,
        )

    async def asyncTearDown(self) -> None:
        await self.event_bus.shutdown()

    async def test_successful_execution_and_verification(self) -> None:
        req = ToolRequest(tool_name="test.fast")
        result = await self.executor.execute(req)

        self.assertTrue(result.success)
        self.assertTrue(result.verified)
        self.assertEqual(result.status, ToolExecutionStatus.SUCCEEDED)
        self.assertEqual(result.output, {"data": "done"})

    async def test_unknown_tool_fails_safely(self) -> None:
        req = ToolRequest(tool_name="unknown.nonexistent")
        result = await self.executor.execute(req)

        self.assertFalse(result.success)
        self.assertFalse(result.verified)
        self.assertEqual(result.status, ToolExecutionStatus.DENIED)
        self.assertIn("Unknown tool", result.error or "")

    async def test_timeout_enforced(self) -> None:
        req = ToolRequest(tool_name="test.slow")
        result = await self.executor.execute(req)

        self.assertFalse(result.success)
        self.assertFalse(result.verified)
        self.assertEqual(result.status, ToolExecutionStatus.TIMEOUT)
        self.assertIn("timed out", result.error or "")

    async def test_verification_failure_reports_failed(self) -> None:
        req = ToolRequest(tool_name="test.unverified")
        result = await self.executor.execute(req)

        self.assertFalse(result.success)
        self.assertFalse(result.verified)
        self.assertEqual(result.status, ToolExecutionStatus.VERIFICATION_FAILED)

    async def test_confirmation_boundary_flow(self) -> None:
        req = ToolRequest(
            request_id="req-confirm-1",
            tool_name="test.confirm",
            arguments={"arg": "val"},
        )

        # 1. First execution attempt without token must hold and return CONFIRMATION_REQUIRED
        result = await self.executor.execute(req)
        self.assertFalse(result.success)
        self.assertEqual(result.status, ToolExecutionStatus.CONFIRMATION_REQUIRED)
        token = result.metadata.get("confirmation_token")
        self.assertIsNotNone(token)

        # 2. Second execution attempt with valid token must succeed
        confirmed_result = await self.executor.execute(req, confirmation_token=token)
        self.assertTrue(confirmed_result.success)
        self.assertTrue(confirmed_result.verified)
        self.assertEqual(confirmed_result.status, ToolExecutionStatus.SUCCEEDED)


if __name__ == "__main__":
    unittest.main()
