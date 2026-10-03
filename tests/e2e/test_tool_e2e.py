"""End-to-End Tests for BUDDY Tool Execution System."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.ai.conversation import ConversationManager
from app.ai.models import MessageRole
from app.ai.provider import MockAIProvider
from app.ai.router import AIRouter
from app.core import BuddyConfig, BuddyState, EventBus, StateMachine
from app.security.authentication import MockAuthenticator
from app.security.confirmation import ConfirmationManager
from app.security.permissions import PermissionEngine
from app.tools.applications import AppOpenTool
from app.tools.executor import ToolExecutor
from app.tools.models import ToolDefinition, ToolRiskLevel
from app.tools.registry import ToolRegistry


class TestToolE2E(unittest.IsolatedAsyncioTestCase):
    """End-to-End tests verifying User/Voice -> AI -> Tool Request -> Permission -> Execution -> Verification -> Response."""

    async def asyncSetUp(self) -> None:
        self.config = BuddyConfig(
            app_env="testing",
            ai_provider="mock",
            tools_enabled=True,
            conversation_max_messages=10,
        )
        self.event_bus = EventBus()
        self.state_machine = StateMachine(BuddyState.IDLE)

        # Set up state transitions on event bus
        self.state_machine.set_transition_callback(
            lambda prev, new, reason, ts: self.event_bus.publish_sync(
                __import__("app.core").core.StateChangedEvent(
                    previous_state=prev, new_state=new, reason=reason, timestamp=ts
                )
            )
        )

        self.registry = ToolRegistry()
        self.registry.register_tool(AppOpenTool())

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

        self.mock_ai = MockAIProvider()
        self.router = AIRouter(self.config)
        self.router.register_provider("mock", self.mock_ai)

        self.conv_mgr = ConversationManager(
            config=self.config,
            event_bus=self.event_bus,
            state_machine=self.state_machine,
            router=self.router,
            tool_executor=self.executor,
        )

    async def asyncTearDown(self) -> None:
        await self.event_bus.shutdown()

    @patch("subprocess.Popen")
    @patch("app.tools.applications._resolve_binary", return_value="C:\\Windows\\notepad.exe")
    async def test_end_to_end_open_notepad_success(
        self, mock_resolve: MagicMock, mock_popen: MagicMock
    ) -> None:
        """PHASE 17 REQUIREMENT:
        Test: User: "Open Notepad" -> AI requests app.open("notepad") ->
        Permission -> ToolExecutor -> Verification -> Final Response.
        """
        # Mock process existence so verification succeeds immediately
        with patch("psutil.process_iter") as mock_iter:
            mock_proc = MagicMock()
            mock_proc.info = {"name": "notepad.exe"}
            mock_iter.return_value = [mock_proc]

            response = await self.conv_mgr.process_user_turn("Open Notepad", voice_response=False)

            # Check that Popen was called safely without shell=True
            mock_popen.assert_called_once_with(["C:\\Windows\\notepad.exe"], close_fds=True)

            # Check that assistant response confirms completed and verified action
            self.assertIn("verified", response.content.lower())

            # Check conversation history contains user, tool result, and assistant
            roles = [m.role for m in self.conv_mgr.history]
            self.assertIn(MessageRole.USER, roles)
            self.assertIn(MessageRole.TOOL, roles)
            self.assertIn(MessageRole.ASSISTANT, roles)

            # Verify tool message has verified=True metadata
            tool_messages = [m for m in self.conv_mgr.history if m.role == MessageRole.TOOL]
            self.assertTrue(len(tool_messages) > 0)
            self.assertTrue(tool_messages[0].metadata.get("verified"))

            # Verify state machine returned to IDLE
            self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    async def test_end_to_end_dangerous_unregistered_operation_fails(self) -> None:
        """PHASE 17 & 18:
        User requests "Delete my important file" -> AI tries to request an unregistered destructive tool -> fails closed.
        """
        # Queue an unregistered tool call from the AI
        self.mock_ai.set_next_tool_calls([{
            "tool_name": "file.delete_all",
            "arguments": {"target": "C:\\important"},
        }])

        response = await self.conv_mgr.process_user_turn("Delete my important file", voice_response=False)

        # AI must report that operation could not be completed / failed
        self.assertIn("could not complete", response.content.lower())

        # Check tool message in history reflects failed/unverified state
        tool_messages = [m for m in self.conv_mgr.history if m.role == MessageRole.TOOL]
        self.assertEqual(len(tool_messages), 1)
        self.assertFalse(tool_messages[0].metadata.get("verified"))


if __name__ == "__main__":
    unittest.main()
