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
    ) -> None:
        self._config = config
        self._event_bus = event_bus
        self._state_machine = state_machine
        self._router = router or AIRouter(config)
        self._voice_pipeline = voice_pipeline
        self._system_prompt = system_prompt
        self._session_id = session_id or str(uuid.uuid4())[:8]

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
        1. Append User Message
        2. Transition State: IDLE -> THINKING (if permitted)
        3. Dispatch to AI Provider
        4. If AI requested tools: Transition THINKING -> EXECUTING -> Run tools -> Verify -> Record TOOL result -> THINKING
        5. Append Assistant Response
        6. If voice_response=True: Transition THINKING -> SPEAKING -> Voicing via TTS -> IDLE
        7. Return AIResponse
        """
        async with self._lock:
            start_turn_time = time.perf_counter()

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

            try:
                # 3. Invoke AI Provider
                ai_start_time = time.perf_counter()
                response = await provider.generate(
                    messages=self._history,
                    system_prompt=self._system_prompt,
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
