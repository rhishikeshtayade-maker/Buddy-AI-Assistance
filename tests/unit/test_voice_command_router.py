"""Tests for BUDDY Typed Voice Command Router and Dispatch Integration."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.tools.models import ToolExecutionStatus, ToolRequest, ToolResult
from app.voice.command_router import VoiceCommandRouter, VoiceIntent, VoiceIntentType
from scripts.voice_assistant import dispatch_voice_intent


class TestVoiceCommandRouter(unittest.TestCase):
    """Verifies typed classification across all intent categories A-L."""

    def setUp(self) -> None:
        self.router = VoiceCommandRouter()

    # A. Battery intent
    def test_scenario_a_battery_intent(self) -> None:
        utterances = [
            "what is my battery level",
            "Hey BUDDY, what is my battery level?",
            "battery status",
            "how much battery",
        ]
        for utt in utterances:
            intent = self.router.classify(utt)
            self.assertEqual(intent.intent_type, VoiceIntentType.TOOL_REQUEST)
            self.assertEqual(intent.tool_name, "system.get_battery")

    # B. Volume intent
    def test_scenario_b_volume_intent(self) -> None:
        utterances = [
            "what is my current volume",
            "Hey BUDDY, what is my current volume?",
            "current volume",
            "system volume",
        ]
        for utt in utterances:
            intent = self.router.classify(utt)
            self.assertEqual(intent.intent_type, VoiceIntentType.TOOL_REQUEST)
            self.assertEqual(intent.tool_name, "system.get_volume")

        # Set volume
        intent_set = self.router.classify("set volume to 30 percent")
        self.assertEqual(intent_set.intent_type, VoiceIntentType.TOOL_REQUEST)
        self.assertEqual(intent_set.tool_name, "system.set_volume")
        self.assertEqual(intent_set.tool_arguments.get("level"), 30)

    # C. Open application
    def test_scenario_c_open_application(self) -> None:
        utterances = [
            ("open Notepad", "notepad"),
            ("Hey BUDDY, open Notepad.", "notepad"),
            ("launch Notepad", "notepad"),
            ("open Calculator", "calc"),
            ("launch calc", "calc"),
        ]
        for utt, expected_app in utterances:
            intent = self.router.classify(utt)
            self.assertEqual(intent.intent_type, VoiceIntentType.TOOL_REQUEST)
            self.assertEqual(intent.tool_name, "app.open")
            self.assertEqual(intent.tool_arguments.get("application"), expected_app)

    # D. Close application
    def test_scenario_d_close_application(self) -> None:
        utterances = [
            ("close Notepad", "notepad"),
            ("Hey BUDDY, close Notepad.", "notepad"),
            ("close Notepad on my screen", "notepad"),
            ("close Calculator", "calc"),
        ]
        for utt, expected_app in utterances:
            intent = self.router.classify(utt)
            self.assertEqual(intent.intent_type, VoiceIntentType.TOOL_REQUEST)
            self.assertEqual(intent.tool_name, "app.close")
            self.assertEqual(intent.tool_arguments.get("application"), expected_app)

    # E. Memory remember
    def test_scenario_e_memory_remember(self) -> None:
        utterances = [
            "remember that my favourite colour is blue",
            "remember that my favorite color is blue",
            "remember my favorite color is blue",
            "Hey BUDDY, remember that my favorite color is blue.",
        ]
        for utt in utterances:
            intent = self.router.classify(utt)
            self.assertEqual(intent.intent_type, VoiceIntentType.MEMORY_REMEMBER)
            self.assertIsNotNone(intent.memory_content)
            self.assertTrue(
                "blue" in intent.memory_content.lower(),
                f"Expected 'blue' in memory content for '{utt}', got '{intent.memory_content}'",
            )

    # F. Memory recall
    def test_scenario_f_memory_recall(self) -> None:
        utterances = [
            "what is my favorite color",
            "what is my favorite color?",
            "what do you remember about my favorite color?",
            "Hey BUDDY, what is my favorite color?",
        ]
        for utt in utterances:
            intent = self.router.classify(utt)
            self.assertEqual(intent.intent_type, VoiceIntentType.MEMORY_RECALL)
            self.assertIsNotNone(intent.target)
            self.assertTrue(
                "favorite color" in intent.target.lower() or "color" in intent.target.lower(),
                f"Expected color in target for '{utt}', got '{intent.target}'",
            )

    # G. Memory forget
    def test_scenario_g_memory_forget(self) -> None:
        utterances = [
            "forget my favorite color",
            "forget that my favorite color is blue",
            "Hey BUDDY, forget my favorite color.",
        ]
        for utt in utterances:
            intent = self.router.classify(utt)
            self.assertEqual(intent.intent_type, VoiceIntentType.MEMORY_FORGET)
            self.assertIsNotNone(intent.target)

    # H. Conversation
    def test_scenario_h_conversation(self) -> None:
        utterances = [
            "what is your name",
            "Hey BUDDY, what is your name?",
            "hello",
            "tell me a joke",
            "explain binary search",
        ]
        for utt in utterances:
            intent = self.router.classify(utt)
            self.assertEqual(intent.intent_type, VoiceIntentType.CONVERSATION)

    # I. Dangerous request
    def test_scenario_i_dangerous_request(self) -> None:
        dangerous_utterances = [
            "delete the Windows system file",
            "Hey BUDDY, delete the Windows system file.",
            "delete system32",
            "wipe windows directory",
            "run powershell",
            "execute cmd",
            "format c:",
            "disable firewall",
        ]
        for utt in dangerous_utterances:
            intent = self.router.classify(utt)
            self.assertEqual(
                intent.intent_type,
                VoiceIntentType.SECURITY_SENSITIVE,
                f"Failed to flag dangerous request '{utt}' as SECURITY_SENSITIVE",
            )
            self.assertIsNotNone(intent.refusal_message)
            self.assertIn("cannot perform", intent.refusal_message.lower())

    # J. Ambiguous request
    def test_scenario_j_ambiguous_request(self) -> None:
        ambiguous = [
            "hmm maybe",
            "well I don't know",
            "fascinating thought",
        ]
        for utt in ambiguous:
            intent = self.router.classify(utt)
            # Must safely fall through to conversation, never a destructive or unintended tool action
            self.assertEqual(intent.intent_type, VoiceIntentType.CONVERSATION)
            self.assertIsNone(intent.tool_name)

    # L. Security boundary
    def test_scenario_l_security_boundary(self) -> None:
        import app.voice.command_router as cr_mod

        # Inspect source code of command_router to prove no execution primitives are used
        with open(cr_mod.__file__, "r", encoding="utf-8") as f:
            code = f.read()

        prohibited_tokens = [
            "import subprocess",
            "from subprocess",
            "subprocess.",
            "os.system",
            "shell=True",
            "eval(",
            "exec(",
            "cmd.exe",
            "powershell.exe",
        ]
        for token in prohibited_tokens:
            self.assertNotIn(
                token,
                code,
                f"Security violation: Router must not reference execution primitive '{token}'",
            )


class TestVoiceDispatchIntegration(unittest.IsolatedAsyncioTestCase):
    """Verifies end-to-end dispatching of typed VoiceIntent through subsystems."""

    async def asyncSetUp(self) -> None:
        self.mock_tool_executor = MagicMock()
        self.mock_memory_manager = MagicMock()
        self.mock_conv_manager = MagicMock()

    # K. Tool verification failure handling
    async def test_scenario_k_tool_verification_failure(self) -> None:
        """Simulate failed tool execution or failed verification. Must give honest failure response."""
        # Case 1: verified=False
        failed_result = ToolResult(
            request_id="test-req-1",
            tool_name="app.close",
            success=False,
            verified=False,
            status=ToolExecutionStatus.VERIFICATION_FAILED,
            error="Process did not terminate within timeout",
        )
        self.mock_tool_executor.execute = AsyncMock(return_value=failed_result)

        intent = VoiceIntent(
            intent_type=VoiceIntentType.TOOL_REQUEST,
            normalized_text="close Notepad",
            tool_name="app.close",
            tool_arguments={"application": "notepad"},
            target="notepad",
        )

        response = await dispatch_voice_intent(
            intent=intent,
            tool_executor=self.mock_tool_executor,
            memory_manager=self.mock_memory_manager,
            conv_manager=self.mock_conv_manager,
        )

        self.assertIn("Failed to close notepad", response)
        self.assertNotIn("Closed Notepad", response)

    async def test_scenario_k_open_app_verification_failure(self) -> None:
        """Simulate open app verification failure."""
        failed_result = ToolResult(
            request_id="test-req-2",
            tool_name="app.open",
            success=False,
            verified=False,
            status=ToolExecutionStatus.FAILED,
            error="Executable not found",
        )
        self.mock_tool_executor.execute = AsyncMock(return_value=failed_result)

        intent = VoiceIntent(
            intent_type=VoiceIntentType.TOOL_REQUEST,
            normalized_text="open Notepad",
            tool_name="app.open",
            tool_arguments={"application": "notepad"},
            target="notepad",
        )

        response = await dispatch_voice_intent(
            intent=intent,
            tool_executor=self.mock_tool_executor,
            memory_manager=self.mock_memory_manager,
            conv_manager=self.mock_conv_manager,
        )

        self.assertIn("Failed to open notepad", response)

    async def test_verified_tool_success_responses(self) -> None:
        """Simulate verified tool execution success."""
        # Verified app.open
        open_result = ToolResult(
            request_id="test-open",
            tool_name="app.open",
            success=True,
            verified=True,
            status=ToolExecutionStatus.SUCCEEDED,
            output={"application": "notepad", "launched": True},
        )
        self.mock_tool_executor.execute = AsyncMock(return_value=open_result)

        intent = VoiceIntent(
            intent_type=VoiceIntentType.TOOL_REQUEST,
            normalized_text="open Notepad",
            tool_name="app.open",
            tool_arguments={"application": "notepad"},
            target="notepad",
        )
        resp = await dispatch_voice_intent(
            intent=intent,
            tool_executor=self.mock_tool_executor,
            memory_manager=self.mock_memory_manager,
            conv_manager=self.mock_conv_manager,
        )
        self.assertEqual(resp, "Opening Notepad.")

        # Verified app.close
        close_result = ToolResult(
            request_id="test-close",
            tool_name="app.close",
            success=True,
            verified=True,
            status=ToolExecutionStatus.SUCCEEDED,
            output={"application": "notepad", "terminated_count": 1},
        )
        self.mock_tool_executor.execute = AsyncMock(return_value=close_result)

        intent_close = VoiceIntent(
            intent_type=VoiceIntentType.TOOL_REQUEST,
            normalized_text="close Notepad",
            tool_name="app.close",
            tool_arguments={"application": "notepad"},
            target="notepad",
        )
        resp_close = await dispatch_voice_intent(
            intent=intent_close,
            tool_executor=self.mock_tool_executor,
            memory_manager=self.mock_memory_manager,
            conv_manager=self.mock_conv_manager,
        )
        self.assertEqual(resp_close, "Closed Notepad.")

    async def test_memory_remember_and_recall_dispatch(self) -> None:
        """Test dispatching to real or mocked memory manager."""
        mock_record = MagicMock()
        mock_record.content = "my favorite color is blue"
        self.mock_memory_manager.remember = AsyncMock(return_value=mock_record)
        self.mock_memory_manager.recall = AsyncMock(return_value=[mock_record])
        self.mock_memory_manager.forget = AsyncMock(return_value=True)

        # Remember
        intent_remember = VoiceIntent(
            intent_type=VoiceIntentType.MEMORY_REMEMBER,
            normalized_text="remember that my favorite color is blue",
            memory_content="my favorite color is blue",
        )
        res_rem = await dispatch_voice_intent(
            intent=intent_remember,
            tool_executor=self.mock_tool_executor,
            memory_manager=self.mock_memory_manager,
            conv_manager=self.mock_conv_manager,
        )
        self.assertIn("my favorite color is blue", res_rem)

        # Recall
        intent_recall = VoiceIntent(
            intent_type=VoiceIntentType.MEMORY_RECALL,
            normalized_text="what is my favorite color",
            target="favorite color",
        )
        res_rec = await dispatch_voice_intent(
            intent=intent_recall,
            tool_executor=self.mock_tool_executor,
            memory_manager=self.mock_memory_manager,
            conv_manager=self.mock_conv_manager,
        )
        self.assertIn("my favorite color is blue", res_rec)

        # Forget
        intent_forget = VoiceIntent(
            intent_type=VoiceIntentType.MEMORY_FORGET,
            normalized_text="forget my favorite color",
            target="favorite color",
        )
        res_forg = await dispatch_voice_intent(
            intent=intent_forget,
            tool_executor=self.mock_tool_executor,
            memory_manager=self.mock_memory_manager,
            conv_manager=self.mock_conv_manager,
        )
        self.assertIn("forgotten", res_forg)

    async def test_security_sensitive_never_executes_tools(self) -> None:
        """Test dangerous request dispatch immediately returns refusal and never calls tool executor."""
        intent = VoiceIntent(
            intent_type=VoiceIntentType.SECURITY_SENSITIVE,
            normalized_text="delete the Windows system file",
            refusal_message="I cannot perform that request because it targets protected system files.",
        )
        res = await dispatch_voice_intent(
            intent=intent,
            tool_executor=self.mock_tool_executor,
            memory_manager=self.mock_memory_manager,
            conv_manager=self.mock_conv_manager,
        )
        self.assertIn("cannot perform", res)
        self.mock_tool_executor.execute.assert_not_called()
        self.mock_conv_manager.process_user_turn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
