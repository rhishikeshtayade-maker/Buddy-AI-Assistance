"""BUDDY AI Provider Interface and Implementations.

Defines the abstract AIProvider contract, deterministic MockAIProvider for CI,
resilient CloudAIProvider with retries and timeout, and LocalAIProvider stub.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.ai.exceptions import (
    AIAuthenticationError,
    AIError,
    AIModelError,
    AIProviderError,
    AIRateLimitError,
    AITimeoutError,
)
from app.ai.models import AIResponse, ChatMessage, MessageRole

logger = logging.getLogger("buddy.ai.provider")


class AIProvider(ABC):
    """Abstract provider interface for generative AI models."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Identifying name of this AI provider."""

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model identifier."""

    @abstractmethod
    async def generate(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> AIResponse:
        """Generate a complete AI response for the given conversation messages."""

    @abstractmethod
    async def generate_stream(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[str]:
        """Stream generated response text tokens incrementally."""


class MockAIProvider(AIProvider):
    """Deterministic mock provider for automated tests and offline environments."""

    def __init__(
        self,
        default_response: str = "Hello! I'm BUDDY, your desktop assistant.",
        model: str = "mock-v1",
        latency: float = 0.0,
        simulate_failure: bool = False,
        failure_exception: Optional[Exception] = None,
    ) -> None:
        self.default_response = default_response
        self._model = model
        self.latency = latency
        self.simulate_failure = simulate_failure
        self.failure_exception = failure_exception
        self.next_tool_calls: Optional[List[Dict[str, Any]]] = None
        self.call_count = 0
        self.last_messages: List[ChatMessage] = []

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def default_model(self) -> str:
        return self._model

    def set_next_response(self, response: str) -> None:
        """Queue a specific text response for the next turn."""
        self.default_response = response

    def set_next_tool_calls(self, tool_calls: List[Dict[str, Any]]) -> None:
        """Queue structured tool calls for the next generation turn."""
        self.next_tool_calls = tool_calls

    async def generate(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> AIResponse:
        start_time = time.perf_counter()
        self.call_count += 1
        self.last_messages = list(messages)

        if self.latency > 0:
            await asyncio.sleep(self.latency)

        if self.simulate_failure:
            err = self.failure_exception or AIProviderError(
                "Simulated mock AI provider failure", provider=self.provider_name
            )
            raise err

        # If explicit tool calls queued, emit them
        if self.next_tool_calls is not None:
            calls = self.next_tool_calls
            self.next_tool_calls = None
            return AIResponse(
                content="",
                finish_reason="tool_calls",
                provider=self.provider_name,
                model=model or self._model,
                tool_calls=calls,
                latency=time.perf_counter() - start_time,
            )

        # Generate intelligent contextual mock reply for common prompts
        reply_content = self.default_response
        if messages:
            last_msg = messages[-1]
            if last_msg.role == MessageRole.TOOL:
                if '"verified": true' in last_msg.content or '"success": true' in last_msg.content:
                    reply_content = "I have completed your request and verified the action."
                elif '"status": "confirmation_required"' in last_msg.content or "confirmation_token" in last_msg.content:
                    reply_content = "This action requires your confirmation before I can proceed."
                elif '"status": "authentication_required"' in last_msg.content:
                    reply_content = "This action requires authentication before I can proceed."
                else:
                    reply_content = "I could not complete the operation because the tool execution or verification failed."
            else:
                last_text = last_msg.content.strip().lower()
                if "what can you do" in last_text:
                    reply_content = "I can assist you with system tasks, answer questions, and control computer operations safely."
                elif "open notepad" in last_text:
                    return AIResponse(
                        content="",
                        finish_reason="tool_calls",
                        provider=self.provider_name,
                        model=model or self._model,
                        tool_calls=[{"tool_name": "app.open", "arguments": {"application": "notepad"}}],
                        latency=time.perf_counter() - start_time,
                    )
                elif "get battery" in last_text or "battery" in last_text:
                    return AIResponse(
                        content="",
                        finish_reason="tool_calls",
                        provider=self.provider_name,
                        model=model or self._model,
                        tool_calls=[{"tool_name": "system.get_battery", "arguments": {}}],
                        latency=time.perf_counter() - start_time,
                    )
                elif "system info" in last_text:
                    return AIResponse(
                        content="",
                        finish_reason="tool_calls",
                        provider=self.provider_name,
                        model=model or self._model,
                        tool_calls=[{"tool_name": "system.get_info", "arguments": {}}],
                        latency=time.perf_counter() - start_time,
                    )
                elif "25 * 4" in last_text or "25 × 4" in last_text or "25*4" in last_text:
                    reply_content = "25 × 4 equals 100."
                elif "joke" in last_text:
                    reply_content = "Why did the computer show up at work cold? Because it left its Windows open!"
                elif "api" in last_text:
                    reply_content = "An API (Application Programming Interface) allows different software applications to communicate with each other."

        elapsed = time.perf_counter() - start_time
        return AIResponse(
            content=reply_content,
            finish_reason="stop",
            provider=self.provider_name,
            model=model or self._model,
            usage={"prompt_tokens": 15, "completion_tokens": 10, "total_tokens": 25},
            latency=elapsed,
        )

    async def generate_stream(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[str]:
        response = await self.generate(
            messages=messages,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            timeout=timeout,
        )
        words = response.content.split(" ")
        for i, word in enumerate(words):
            yield word + (" " if i < len(words) - 1 else "")
            await asyncio.sleep(0.005)


class CloudAIProvider(AIProvider):
    """Resilient cloud AI provider supporting OpenAI-compatible chat endpoints."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries

    @property
    def provider_name(self) -> str:
        return "cloud"

    @property
    def default_model(self) -> str:
        return self._model

    def _prepare_payload(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str],
        model: Optional[str],
        temperature: float,
        max_tokens: int,
        tools: Optional[List[Dict[str, Any]]],
        stream: bool = False,
    ) -> Dict[str, Any]:
        payload_messages: List[Dict[str, Any]] = []

        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            payload_messages.append(msg.to_dict())

        payload: Dict[str, Any] = {
            "model": model or self._model,
            "messages": payload_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        if tools:
            payload["tools"] = tools

        return payload

    async def generate(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> AIResponse:
        if not self._api_key:
            raise AIAuthenticationError(
                "Cloud AI API key is not configured. Set BUDDY_AI_API_KEY or AI_API_KEY.",
                provider=self.provider_name,
            )

        payload = self._prepare_payload(
            messages=messages,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            stream=False,
        )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        url = f"{self._base_url}/chat/completions"
        effective_timeout = timeout or self._timeout
        start_time = time.perf_counter()

        attempt = 0
        backoff = 1.0

        while True:
            attempt += 1
            try:
                async with httpx.AsyncClient(timeout=effective_timeout) as client:
                    resp = await client.post(url, json=payload, headers=headers)

                # Authentication error (do not retry)
                if resp.status_code in (401, 403):
                    raise AIAuthenticationError(
                        f"Authentication failed (HTTP {resp.status_code}): {resp.text}",
                        provider=self.provider_name,
                        status_code=resp.status_code,
                    )

                # Rate limit (429)
                if resp.status_code == 429:
                    retry_after_hdr = resp.headers.get("Retry-After")
                    retry_after = float(retry_after_hdr) if retry_after_hdr else backoff
                    if attempt <= self._max_retries:
                        logger.warning("Cloud AI rate-limited (429). Retrying after %.1fs...", retry_after)
                        await asyncio.sleep(retry_after)
                        backoff = min(backoff * 2, 8.0)
                        continue
                    raise AIRateLimitError(
                        "Cloud AI rate limit exceeded",
                        retry_after=retry_after,
                        provider=self.provider_name,
                    )

                # Client error (400, etc. - do not retry)
                if 400 <= resp.status_code < 500:
                    raise AIModelError(
                        f"Cloud AI client error (HTTP {resp.status_code}): {resp.text}",
                        provider=self.provider_name,
                        status_code=resp.status_code,
                    )

                # Server error (500, 502, 503 - transient, retryable)
                if resp.status_code >= 500:
                    if attempt <= self._max_retries:
                        logger.warning(
                            "Cloud AI server error (HTTP %d). Retry %d/%d after %.1fs...",
                            resp.status_code,
                            attempt,
                            self._max_retries,
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                        backoff = min(backoff * 2, 8.0)
                        continue
                    raise AIProviderError(
                        f"Cloud AI server error (HTTP {resp.status_code}) after {attempt} attempts",
                        provider=self.provider_name,
                        status_code=resp.status_code,
                    )

                # Successful response (200 OK)
                data = resp.json()
                elapsed = time.perf_counter() - start_time
                choice = data["choices"][0]
                content = choice.get("message", {}).get("content", "") or ""
                finish_reason = choice.get("finish_reason", "stop")
                usage = data.get("usage")

                return AIResponse(
                    content=content,
                    finish_reason=finish_reason,
                    provider=self.provider_name,
                    model=data.get("model", model or self._model),
                    usage=usage,
                    latency=elapsed,
                )

            except httpx.TimeoutException as e:
                if attempt <= self._max_retries:
                    logger.warning("Cloud AI request timed out. Retrying attempt %d/%d...", attempt, self._max_retries)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8.0)
                    continue
                raise AITimeoutError(
                    f"Cloud AI request timed out after {effective_timeout}s: {e}",
                    provider=self.provider_name,
                ) from e

            except httpx.RequestError as e:
                if attempt <= self._max_retries:
                    logger.warning("Network connectivity error: %s. Retrying attempt %d/%d...", e, attempt, self._max_retries)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 8.0)
                    continue
                raise AIProviderError(
                    f"Cloud AI network connectivity failed: {e}",
                    provider=self.provider_name,
                ) from e

    async def generate_stream(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[str]:
        if not self._api_key:
            raise AIAuthenticationError("Cloud AI API key is not configured.", provider=self.provider_name)

        payload = self._prepare_payload(
            messages=messages,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            stream=True,
        )

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        url = f"{self._base_url}/chat/completions"
        effective_timeout = timeout or self._timeout

        try:
            async with httpx.AsyncClient(timeout=effective_timeout) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code != 200:
                        raise AIProviderError(
                            f"Streaming request failed with HTTP {response.status_code}",
                            provider=self.provider_name,
                            status_code=response.status_code,
                        )

                    async for line in response.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            delta = chunk["choices"][0].get("delta", {}).get("content", "")
                            if delta:
                                yield delta
                        except Exception:
                            continue
        except Exception as e:
            if isinstance(e, AIError):
                raise
            raise AIProviderError(f"Cloud AI streaming error: {e}", provider=self.provider_name) from e


class LocalAIProvider(AIProvider):
    """Local offline AI provider interface (Ollama / Local LLM integration point)."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2:latest",
        timeout: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout

    @property
    def provider_name(self) -> str:
        return "local"

    @property
    def default_model(self) -> str:
        return self._model

    async def generate(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> AIResponse:
        url = f"{self._base_url}/api/chat"
        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        for m in messages:
            payload_messages.append(m.to_dict())

        payload = {
            "model": model or self._model,
            "messages": payload_messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }

        try:
            async with httpx.AsyncClient(timeout=timeout or self._timeout) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code != 200:
                    raise AIProviderError(
                        f"Local model error (HTTP {resp.status_code}): {resp.text}",
                        provider=self.provider_name,
                        status_code=resp.status_code,
                    )
                data = resp.json()
                content = data.get("message", {}).get("content", "")
                return AIResponse(
                    content=content,
                    provider=self.provider_name,
                    model=model or self._model,
                    latency=data.get("total_duration", 0) / 1e9,
                )
        except (httpx.ConnectError, httpx.RequestError, httpx.TimeoutException) as err:
            raise AIProviderError(
                f"Local AI provider unavailable at {self._base_url}. Ensure Ollama or local LLM server is running.",
                provider=self.provider_name,
            ) from err
        except Exception as err:
            if isinstance(err, AIError):
                raise
            raise AIProviderError(f"Local AI generation error: {err}", provider=self.provider_name) from err

    async def generate_stream(
        self,
        messages: List[ChatMessage],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[str]:
        # Fallback to complete generation
        full = await self.generate(
            messages=messages,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            timeout=timeout,
        )
        yield full.content
