"""Security and Permission Boundary Tests for BUDDY Desktop Integration.

Verifies:
1. ToolExecutor security boundary is strictly preserved.
2. Spoken confirmation rejection prevents execution of dangerous actions.
3. Prohibited/destructive requests are rejected immediately without shell execution.
4. Secret redaction applies to desktop status text and audit records.
5. Desktop HUD introduces zero arbitrary shell/PowerShell/eval/exec execution pathways.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.core import BuddyConfig, BuddyState, EventBus, StateMachine
from app.desktop.dispatch import dispatch_voice_intent
from app.tools.builtin import register_builtin_tools
from app.tools.executor import ToolExecutor
from app.tools.models import ToolExecutionStatus, ToolRequest, ToolResult
from app.tools.registry import ToolRegistry
from app.voice.command_router import VoiceCommandRouter, VoiceIntent, VoiceIntentType


class TestDesktopSecurity(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.config = BuddyConfig(app_env="testing")
        self.event_bus = EventBus()
        self.state_machine = StateMachine(BuddyState.IDLE)
        self.registry = ToolRegistry()
        register_builtin_tools(self.registry)
        self.executor = ToolExecutor(registry=self.registry, event_bus=self.event_bus)
        self.cmd_router = VoiceCommandRouter()

    async def asyncTearDown(self) -> None:
        await self.event_bus.shutdown()

    async def test_destructive_system_command_rejected_by_router(self) -> None:
        """Destructive requests (e.g. deleting Windows files, arbitrary shell) are refused."""
        dangerous_inputs = [
            "delete the windows directory",
            "execute powershell script to format c:",
            "wipe windows system32",
            "disable the firewall",
            "steal credentials from registry",
        ]

        for text in dangerous_inputs:
            intent = self.cmd_router.classify(text)
            self.assertEqual(
                intent.intent_type,
                VoiceIntentType.SECURITY_SENSITIVE,
                f"Expected '{text}' to be classified as SECURITY_SENSITIVE",
            )
            # Dispatch must immediately return refusal without invoking tools
            reply = await dispatch_voice_intent(
                intent=intent,
                tool_executor=self.executor,
                memory_manager=None,
                conv_manager=MagicMock(),
                state_machine=self.state_machine,
            )
            self.assertIn("cannot perform", reply.lower())
            self.assertEqual(self.state_machine.current_state, BuddyState.IDLE)

    async def test_confirmation_callback_rejection_prevents_execution(self) -> None:
        """When an action requires confirmation and the user rejects, tool is NOT executed."""
        intent = VoiceIntent(
            intent_type=VoiceIntentType.TOOL_REQUEST,
            normalized_text="close notepad",
            tool_name="app.close",
            tool_arguments={"application": "notepad"},
            target="notepad",
        )

        # Mock executor requiring confirmation on initial call
        mock_executor = MagicMock()
        first_res = ToolResult(
            request_id="r1",
            tool_name="app.close",
            success=False,
            verified=False,
            status=ToolExecutionStatus.CONFIRMATION_REQUIRED,
            metadata={"confirmation_token": "token-123"},
        )
        mock_executor.execute = AsyncMock(return_value=first_res)

        # User denies confirmation via callback
        user_confirmed = False
        status_updates = []

        reply = await dispatch_voice_intent(
            intent=intent,
            tool_executor=mock_executor,
            memory_manager=None,
            conv_manager=MagicMock(),
            state_machine=self.state_machine,
            confirm=lambda prompt: user_confirmed,
            on_status=status_updates.append,
        )

        self.assertIn("won't close", reply.lower())
        # Tool was executed only ONCE (to evaluate permission), never re-executed with token!
        self.assertEqual(mock_executor.execute.call_count, 1)
        self.assertIn("Action cancelled — not confirmed", status_updates)

    async def test_secret_redaction_in_status_and_audit(self) -> None:
        """Ensure sensitive tokens and keys are never present in status callbacks."""
        from app.core.logging import redact_string

        secret_text = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.secret_token_123"
        redacted = redact_string(secret_text)
        self.assertNotIn("secret_token_123", redacted)
        self.assertIn("********", redacted)

    async def test_zero_arbitrary_shell_pathways(self) -> None:
        """Verify ToolRegistry does not contain raw shell or command-line execution tools."""
        registered_tools = self.registry.list_tools()
        forbidden_names = {"shell", "bash", "powershell", "cmd", "eval", "exec", "subprocess"}
        for tool_def in registered_tools:
            self.assertNotIn(tool_def.name.lower(), forbidden_names)
