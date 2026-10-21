"""BUDDY Voice Intent Dispatcher.

Single authoritative dispatcher that routes a classified ``VoiceIntent`` to the
appropriate subsystem (ToolExecutor, MemoryManager, ConversationManager).

Moved here from ``scripts/voice_assistant.py`` (Loop 15) so that both the
console assistant and the persistent desktop runtime share one implementation.
``scripts/voice_assistant.py`` re-exports these names for backward compatibility.

Security boundary (unchanged):
    ToolRegistry -> ToolExecutor -> PermissionEngine -> ConfirmationManager /
    Authentication -> Execution -> Verification -> Audit

This module NEVER executes shell, PowerShell, cmd, eval/exec or child processes.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Awaitable, Callable, Optional, Union

from app.core import BuddyState, StateMachine
from app.core.exceptions import MemoryPolicyViolationError
from app.tools.models import ToolExecutionStatus, ToolRequest
from app.voice.command_router import VoiceIntent, VoiceIntentType

logger = logging.getLogger("buddy.desktop.dispatch")

# A confirmation callback receives a short human-readable description of the
# pending action and returns True only if the user explicitly approved it.
ConfirmCallback = Callable[[str], Union[bool, Awaitable[bool]]]
# Optional observer notified of honest, user-facing action status text.
StatusCallback = Callable[[str], Any]


def recover_state_to_idle(state_machine: StateMachine, reason: str = "Turn cycle recovery") -> None:
    """Ensure the state machine returns safely to IDLE without leaving the runtime stuck."""
    current = state_machine.current_state
    if current == BuddyState.IDLE:
        return
    if state_machine.can_transition_to(BuddyState.IDLE):
        state_machine.transition_to(BuddyState.IDLE, reason=reason)
    elif state_machine.can_transition_to(BuddyState.SPEAKING):
        state_machine.transition_to(BuddyState.SPEAKING, reason=reason)
        if state_machine.can_transition_to(BuddyState.IDLE):
            state_machine.transition_to(BuddyState.IDLE, reason="Recovery from speaking")
    elif state_machine.can_transition_to(BuddyState.ERROR):
        state_machine.transition_to(BuddyState.ERROR, reason=reason)
        if state_machine.can_transition_to(BuddyState.IDLE):
            state_machine.transition_to(BuddyState.IDLE, reason="Recovery from error")


def describe_tool_action(intent: VoiceIntent) -> str:
    """Return a short, non-sensitive description of a pending tool action."""
    target = intent.target or intent.tool_arguments.get("application") or ""
    if intent.tool_name == "app.close":
        return f"close {target or 'the application'}"
    if intent.tool_name == "app.open":
        return f"open {target or 'the application'}"
    if intent.tool_name == "system.set_volume":
        return f"set the volume to {intent.tool_arguments.get('level', 'the requested level')}%"
    return f"run {intent.tool_name}"


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def dispatch_voice_intent(
    intent: VoiceIntent,
    tool_executor: Any,
    memory_manager: Optional[Any],
    conv_manager: Any,
    state_machine: Optional[StateMachine] = None,
    confirm: Optional[ConfirmCallback] = None,
    on_status: Optional[StatusCallback] = None,
) -> str:
    """Safely dispatch a recognized voice intent to the appropriate subsystem.

    Args:
        confirm: Optional explicit-approval callback. When provided, a
            ``CONFIRMATION_REQUIRED`` tool result is only re-submitted with its
            token if ``confirm`` returns True. The desktop runtime always
            supplies this. When omitted, the legacy console behaviour is kept.
        on_status: Optional observer for honest action status text.
    """

    def _status(text: str) -> None:
        if on_status is not None:
            try:
                on_status(text)
            except Exception:  # pragma: no cover - observer must never break dispatch
                logger.debug("Status observer failed", exc_info=True)

    # 1. Prohibited / dangerous security-sensitive requests
    if intent.intent_type == VoiceIntentType.SECURITY_SENSITIVE:
        _status("Request refused by security policy")
        return intent.refusal_message or (
            "I cannot perform that request because it targets protected system files or restricted operations."
        )

    # 2. Structured tool request (always through ToolExecutor)
    if intent.intent_type == VoiceIntentType.TOOL_REQUEST:
        if not intent.tool_name:
            return "I could not determine which tool was requested."

        if state_machine and state_machine.can_transition_to(BuddyState.EXECUTING):
            state_machine.transition_to(
                BuddyState.EXECUTING,
                reason=f"Executing tool: {intent.tool_name}",
            )
        try:
            req = ToolRequest(
                tool_name=intent.tool_name,
                arguments=intent.tool_arguments,
                requested_by="user_voice",
            )
            _status(f"Requesting {intent.tool_name}…")
            res = await tool_executor.execute(req)

            if res.status == ToolExecutionStatus.CONFIRMATION_REQUIRED and "confirmation_token" in res.metadata:
                token = res.metadata["confirmation_token"]
                if confirm is not None:
                    _status(f"Waiting for your confirmation to {describe_tool_action(intent)}")
                    approved = bool(await _maybe_await(confirm(describe_tool_action(intent))))
                    if not approved:
                        _status("Action cancelled — not confirmed")
                        return f"Okay, I won't {describe_tool_action(intent)}."
                # Token is single-use and bound to request id/tool/arguments by ConfirmationManager.
                res = await tool_executor.execute(req, confirmation_token=token)

            # Strict empirical verification: never claim success on unverified or failed operations
            if not (res.success and res.verified):
                error_reason = res.error or "Action verification failed."
                _status("Action failed or could not be verified")
                if intent.tool_name == "app.open":
                    return f"Failed to open {intent.target or 'the application'}."
                elif intent.tool_name == "app.close":
                    return f"Failed to close {intent.target or 'the application'}."
                elif intent.tool_name == "system.set_volume":
                    return "Failed to adjust volume."
                else:
                    return f"I could not complete that request: {error_reason}"

            _status("Action verified")
            if intent.tool_name == "system.get_battery":
                if isinstance(res.output, dict):
                    percent = res.output.get("percent", "unknown")
                    plugged = res.output.get("power_plugged", False)
                    status = "plugged in" if plugged else "running on battery"
                    return f"Your battery is at {percent}% and is currently {status}."
                return "Battery status checked successfully."
            elif intent.tool_name == "system.get_volume":
                if isinstance(res.output, dict):
                    vol = res.output.get("volume", "unknown")
                    return f"The current system volume is at {vol}%."
                return "Volume checked successfully."
            elif intent.tool_name == "system.set_volume":
                level = intent.tool_arguments.get("level", "the requested level")
                return f"System volume set to {level}%."
            elif intent.tool_name == "app.open":
                app_label = (intent.target or "application").capitalize()
                return f"Opening {app_label}."
            elif intent.tool_name == "app.close":
                app_label = (intent.target or "application").capitalize()
                return f"Closed {app_label}."
            else:
                return f"Successfully completed {intent.tool_name}."
        finally:
            if state_machine and state_machine.current_state == BuddyState.EXECUTING:
                if state_machine.can_transition_to(BuddyState.THINKING):
                    state_machine.transition_to(BuddyState.THINKING, reason="Tool execution finished")

    # 3. Explicit memory storage
    if intent.intent_type == VoiceIntentType.MEMORY_REMEMBER:
        if not memory_manager:
            return "Memory storage is currently unavailable."
        content = intent.memory_content or intent.normalized_text
        try:
            rec = await memory_manager.remember(content)
            return f"I'll remember that: {rec.content}."
        except MemoryPolicyViolationError as pe:
            return f"I cannot store that memory: {pe.message}"
        except Exception as e:
            return f"Failed to store memory: {e}"

    # 4. Explicit memory recall
    if intent.intent_type == VoiceIntentType.MEMORY_RECALL:
        if not memory_manager:
            return "Memory is currently unavailable."
        target = intent.target or intent.memory_content or intent.normalized_text
        try:
            records = await memory_manager.recall(target)
            if records:
                return f"I remember that {records[0].content}."
            return f"I don't have any saved memory about '{target}'."
        except Exception as e:
            return f"Failed to recall memory: {e}"

    # 5. Explicit memory forget
    if intent.intent_type == VoiceIntentType.MEMORY_FORGET:
        if not memory_manager:
            return "Memory is currently unavailable."
        target = intent.target or intent.memory_content or intent.normalized_text
        try:
            success = await memory_manager.forget(target)
            if success:
                return f"I have forgotten your preference regarding '{target}'."
            return f"I could not find any saved memory matching '{target}'."
        except Exception as e:
            return f"Failed to remove memory: {e}"

    # 6. Conversational AI fallback
    if intent.direct_response:
        return intent.direct_response

    response = await conv_manager.process_user_turn(intent.normalized_text, voice_response=False)
    return response.content
