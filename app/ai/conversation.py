"""BUDDY Conversation Manager.

Coordinates multi-turn dialogue history, context truncation limits,
system instructions, AI provider invocation, voice pipeline integration,
and state machine progression.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

from app.ai.events import (
    AIRequestStartedEvent,
    AIResponseReceivedEvent,
    ConversationEndedEvent,
    ConversationErrorEvent,
    ConversationStartedEvent,
    UserMessageReceivedEvent,
)
from app.ai.exceptions import AIError, ConversationError
from app.ai.models import AIResponse, ChatMessage, ContentSource, MessageRole
from app.ai.prompts import BUDDY_SYSTEM_PROMPT, wrap_untrusted_content
from app.ai.router import AIRouter
from app.core import BuddyState, EventBus, StateMachine
from app.core.config import BuddyConfig
from app.tools.builtin import register_builtin_tools
from app.tools.executor import ToolExecutor
from app.tools.models import ToolRequest
from app.tools.registry import ToolRegistry
from app.voice.pipeline import VoicePipeline

logger = logging.getLogger("buddy.ai.conversation")


class ConversationManager:
    """Manages conversational dialogue context, AI request dispatch, and voice turn coordination."""

    def __init__(
        self,
        config: BuddyConfig,
        event_bus: EventBus,
        state_machine: StateMachine,
        router: Optional[AIRouter] = None,
        voice_pipeline: Optional[VoicePipeline] = None,
        tool_executor: Optional[ToolExecutor] = None,
        system_prompt: str = BUDDY_SYSTEM_PROMPT,
        session_id: Optional[str] = None,
        memory_manager: Optional[Any] = None,
    ) -> None:
        self._config = config
        self._event_bus = event_bus
        self._state_machine = state_machine
        self._router = router or AIRouter(config)
        self._voice_pipeline = voice_pipeline
        self._system_prompt = system_prompt
        self._session_id = session_id or str(uuid.uuid4())[:8]
        self._memory_manager = memory_manager

        # Initialize Tool Execution Layer
        if tool_executor is not None:
            self._tool_executor: Optional[ToolExecutor] = tool_executor
        elif config.tools_enabled:
            registry = ToolRegistry()
            register_builtin_tools(registry)
            self._tool_executor = ToolExecutor(
                registry=registry,
                event_bus=self._event_bus,
                default_timeout=config.tools_timeout,
            )
        else:
            self._tool_executor = None

        self._history: List[ChatMessage] = []
        self._max_messages = config.conversation_max_messages
        self._lock = asyncio.Lock()

        # Latency tracking
        self.last_ai_latency: float = 0.0
        self.last_total_turn_latency: float = 0.0

        # Subscribe to VoiceCommandReceivedEvent if voice pipeline is wired
        self._event_bus.subscribe(
            __import__("app.voice").voice.VoiceCommandReceivedEvent,
            self._on_voice_command_received,
        )

    @property
    def tool_executor(self) -> Optional[ToolExecutor]:
        return self._tool_executor

    def set_tool_executor(self, executor: ToolExecutor) -> None:
        """Attach a tool executor for tool dispatch."""
        self._tool_executor = executor

    @property
    def memory_manager(self) -> Optional[Any]:
        return self._memory_manager

    def set_memory_manager(self, manager: Any) -> None:
        """Attach a memory manager for contextual personalization and user preference storage."""
        self._memory_manager = manager

    async def _handle_memory_command(self, cmd: Any, raw_text: str) -> str:
        from app.core.exceptions import MemoryPolicyViolationError
        from app.memory.models import MemoryCommandAction

        action = cmd.action
        if action == MemoryCommandAction.CLEAR_SESSION:
            count = await self._memory_manager.clear_session()
            return f"I have cleared your temporary session memory ({count} entries removed)."
        elif action == MemoryCommandAction.CLEAR_ALL:
            count = await self._memory_manager.clear_long_term()
            return f"I have cleared all long-term memories ({count} entries removed)."
        elif action == MemoryCommandAction.SHOW:
            records = await self._memory_manager.list_memories(limit=10)
            if not records:
                return "I don't have any saved memories about your preferences yet."
            items = [f"- {r.content} ({r.memory_type.value})" for r in records]
            return "Here is what I remember about your preferences:\n" + "\n".join(items)
        elif action == MemoryCommandAction.FORGET:
            target = cmd.target_content or raw_text
            success = await self._memory_manager.forget(target)
            if success:
                return f"I have forgotten your preference regarding '{target}'."
            return f"I could not find any saved memory matching '{target}'."
        elif action == MemoryCommandAction.REMEMBER:
            target = cmd.target_content or raw_text
            try:
                rec = await self._memory_manager.remember(target)
                return f"I'll remember that: {rec.content}."
            except MemoryPolicyViolationError as pe:
                return f"I cannot store that memory: {pe.message}"
            except Exception as e:
                return f"Failed to store memory: {e}"
        return "Memory command processed."

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def history(self) -> List[ChatMessage]:
        return list(self._history)

    @property
    def router(self) -> AIRouter:
        return self._router

    @property
    def voice_pipeline(self) -> Optional[VoicePipeline]:
        return self._voice_pipeline

    def set_voice_pipeline(self, pipeline: VoicePipeline) -> None:
        """Attach a voice pipeline for speech input and TTS voicing."""
        self._voice_pipeline = pipeline

    async def clear_history(self) -> None:
        """Clear active conversation dialogue history."""
        total_turns = len(self._history)
        self._history.clear()
        await self._event_bus.publish(
            ConversationEndedEvent(session_id=self._session_id, total_turns=total_turns)
        )
        logger.debug("Conversation session %s history cleared.", self._session_id)

    def _truncate_history_if_needed(self) -> None:
        """Ensure conversation history does not exceed configured message limits."""
        if len(self._history) > self._max_messages:
            # Keep newest messages within limit
            overflow = len(self._history) - self._max_messages
            self._history = self._history[overflow:]
            logger.debug("Truncated %d oldest messages from conversation history.", overflow)

    async def _on_voice_command_received(self, event: Any) -> None:
        """Handle incoming transcribed voice command from Loop 2 Voice Pipeline."""
        transcript = getattr(event, "transcript", "")
        if not transcript or not transcript.strip():
            logger.debug("Empty voice command transcript ignored.")
            return

        logger.info("Voice command received: '%s'", transcript)
        await self.process_user_turn(transcript, voice_response=True)

    async def process_user_turn(
        self,
        user_text: str,
        source: ContentSource = ContentSource.USER_INPUT,
        provider_override: Optional[str] = None,
        voice_response: bool = False,
        confirmation_token: Optional[str] = None,
        auth_credential: Optional[str] = None,
    ) -> AIResponse:
        """Execute a full conversational turn for user input.

        Flow:
        1. Check natural language memory commands (remember, forget, show, clear)
        2. Append User Message
        3. Recall relevant contextual memories (untrusted context)
        4. Transition State: IDLE -> THINKING
        5. Dispatch to AI Provider with recalled memory context
        6. Handle Tools if emitted
        7. Append Assistant Response
        8. Return AIResponse
        """
        async with self._lock:
            start_turn_time = time.perf_counter()

            # Handle natural language memory commands if memory manager attached
            if self._memory_manager:
                mem_cmd = self._memory_manager.parse_memory_command(user_text)
                if mem_cmd:
                    resp_content = await self._handle_memory_command(mem_cmd, user_text)
                    response = AIResponse(
                        content=resp_content,
                        provider="memory_manager",
                        model="internal",
                        tool_calls=[],
                    )
                    self._history.append(ChatMessage(role=MessageRole.USER, content=user_text, source=source))
                    self._history.append(ChatMessage(role=MessageRole.ASSISTANT, content=resp_content, source=ContentSource.INTERNAL))
                    self._truncate_history_if_needed()
                    if self._state_machine.can_transition_to(BuddyState.IDLE):
                        self._state_machine.transition_to(BuddyState.IDLE, reason="Memory command handled")
                    return response

            if not self._history:
                await self._event_bus.publish(
                    ConversationStartedEvent(
                        session_id=self._session_id,
                        provider=provider_override or self._config.ai_provider,
                        model=self._config.ai_model,
                    )
                )

            # 1. Format content if from untrusted external source
            content = user_text
            if source == ContentSource.UNTRUSTED_EXTERNAL:
                content = wrap_untrusted_content(user_text, source="external")

            user_msg = ChatMessage(
                role=MessageRole.USER,
                content=content,
                source=source,
            )
            self._history.append(user_msg)
            self._truncate_history_if_needed()

            await self._event_bus.publish(
                UserMessageReceivedEvent(
                    session_id=self._session_id,
                    content_length=len(content),
                    source=source.value,
                )
            )

            # 2. State Machine: Transition to THINKING
            if self._state_machine.can_transition_to(BuddyState.THINKING):
                self._state_machine.transition_to(
                    BuddyState.THINKING,
                    reason="Processing conversational turn",
                )

            provider = self._router.get_provider(provider_override)

            await self._event_bus.publish(
                AIRequestStartedEvent(
                    session_id=self._session_id,
                    provider=provider.provider_name,
                    model=self._config.ai_model,
                    message_count=len(self._history),
                )
            )

            # 3. Retrieve relevant memories for bounded context injection
            effective_system_prompt = self._system_prompt
            if self._memory_manager:
                try:
                    recalled = await self._memory_manager.recall(
                        user_text,
                        limit=self._config.memory_max_context_records,
                    )
                    recalled_block = self._memory_manager.format_for_context(recalled)
                    if recalled_block:
                        effective_system_prompt = f"{self._system_prompt}\n\n{recalled_block}"
                except Exception as e:
                    logger.warning("Failed to recall memories for conversational turn: %s", e)

            try:
                # 4. Invoke AI Provider
                ai_start_time = time.perf_counter()
                response = await provider.generate(
                    messages=self._history,
                    system_prompt=effective_system_prompt,
                    model=self._config.ai_model,
                    temperature=self._config.ai_temperature,
                    max_tokens=self._config.ai_max_tokens,
                    timeout=self._config.ai_timeout,
                )
                self.last_ai_latency = time.perf_counter() - ai_start_time

                # 4. Handle Tool Requests if emitted by the AI model
                if response.tool_calls and self._tool_executor is not None:
                    # Transition THINKING -> EXECUTING
                    if self._state_machine.can_transition_to(BuddyState.EXECUTING):
                        self._state_machine.transition_to(
                            BuddyState.EXECUTING,
                            reason="Executing requested tools",
                        )

                    calls_to_run = response.tool_calls[: self._config.tools_max_per_turn]
                    for call in calls_to_run:
                        t_name = call.get("tool_name") or call.get("name") or ""
                        t_args = call.get("arguments", {})
                        if isinstance(t_args, str):
                            try:
                                t_args = json.loads(t_args)
                            except Exception:
                                t_args = {"raw": t_args}

                        req = ToolRequest(
                            request_id=call.get("id") or str(uuid.uuid4()),
                            tool_name=t_name,
                            arguments=t_args,
                            conversation_id=self._session_id,
                        )
                        result = await self._tool_executor.execute(
                            req,
                            confirmation_token=confirmation_token,
                            auth_credential=auth_credential,
                        )

                        # Wrap raw output for Prompt Injection defense (Phase 12)
                        raw_out_str = json.dumps(result.output, default=str) if result.output is not None else ""
                        wrapped_out = wrap_untrusted_content(raw_out_str, source=f"tool:{t_name}")

                        tool_content = json.dumps({
                            "tool_name": t_name,
                            "success": result.success,
                            "verified": result.verified,
                            "status": result.status.value,
                            "output": wrapped_out,
                            "error": result.error,
                        })
                        tool_msg = ChatMessage(
                            role=MessageRole.TOOL,
                            content=tool_content,
                            source=ContentSource.TOOL_RESULT,
                            metadata={"tool_name": t_name, "verified": result.verified, "status": result.status.value},
                        )
                        self._history.append(tool_msg)
                        self._truncate_history_if_needed()

                    # Transition back to THINKING
                    if self._state_machine.can_transition_to(BuddyState.THINKING):
                        self._state_machine.transition_to(
                            BuddyState.THINKING,
                            reason="Synthesizing final response following tool execution",
                        )

                    # Synthesize final response from AI
                    response = await provider.generate(
                        messages=self._history,
                        system_prompt=self._system_prompt,
                        model=self._config.ai_model,
                        temperature=self._config.ai_temperature,
                        max_tokens=self._config.ai_max_tokens,
                        timeout=self._config.ai_timeout,
                    )

                # 5. Append Assistant Response
                assistant_msg = ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=response.content,
                    source=ContentSource.INTERNAL,
                )
                self._history.append(assistant_msg)
                self._truncate_history_if_needed()

                await self._event_bus.publish(
                    AIResponseReceivedEvent(
                        session_id=self._session_id,
                        provider=response.provider,
                        model=response.model,
                        content=response.content,
                        latency=response.latency,
                        finish_reason=response.finish_reason,
                    )
                )

                # 5. Voice Response Integration (TTS)
                if voice_response and self._voice_pipeline is not None:
                    # Transition THINKING -> SPEAKING
                    if self._state_machine.can_transition_to(BuddyState.SPEAKING):
                        self._state_machine.transition_to(
                            BuddyState.SPEAKING,
                            reason="Voicing AI response through TTS",
                        )

                    try:
                        await self._voice_pipeline.speak(response.content)
                    finally:
                        # Transition SPEAKING -> IDLE
                        if self._state_machine.can_transition_to(BuddyState.IDLE):
                            self._state_machine.transition_to(
                                BuddyState.IDLE,
                                reason="Speech playback completed",
                            )
                else:
                    # Non-voice turn: Transition THINKING -> IDLE
                    # In our state machine: THINKING can transition to EXECUTING, SPEAKING, ERROR, SHUTTING_DOWN
                    # To return to IDLE cleanly without speaking, we can transition SPEAKING -> IDLE or recovery
                    if self._state_machine.can_transition_to(BuddyState.SPEAKING):
                        self._state_machine.transition_to(BuddyState.SPEAKING, reason="Turn response ready")
                        if self._state_machine.can_transition_to(BuddyState.IDLE):
                            self._state_machine.transition_to(BuddyState.IDLE, reason="Turn complete")

                self.last_total_turn_latency = time.perf_counter() - start_turn_time
                return response

            except Exception as err:
                self.last_total_turn_latency = time.perf_counter() - start_turn_time
                logger.error("Error during conversation turn: %s", err, exc_info=True)

                await self._event_bus.publish(
                    ConversationErrorEvent(
                        session_id=self._session_id,
                        error_type=type(err).__name__,
                        message=str(err),
                    )
                )

                # State Recovery: THINKING -> ERROR -> IDLE
                if self._state_machine.can_transition_to(BuddyState.ERROR):
                    self._state_machine.transition_to(BuddyState.ERROR, reason=f"AI failure: {err}")
                    if self._state_machine.can_transition_to(BuddyState.IDLE):
                        self._state_machine.transition_to(BuddyState.IDLE, reason="Recovery from AI error")

                raise
