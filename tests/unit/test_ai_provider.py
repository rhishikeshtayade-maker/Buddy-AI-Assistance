"""Unit tests for BUDDY AI Providers (Mock, Cloud, Local)."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.ai import (
    AIAuthenticationError,
    AIError,
    AIModelError,
    AIProviderError,
    AIRateLimitError,
    AITimeoutError,
    ChatMessage,
    CloudAIProvider,
    LocalAIProvider,
    MessageRole,
    MockAIProvider,
)


class TestAIProviders(unittest.IsolatedAsyncioTestCase):
    """Test suite verifying AIProvider implementations, streaming, and error handling."""

    async def asyncSetUp(self) -> None:
        self.mock_provider = MockAIProvider(model="mock-v1")
        self.messages = [ChatMessage(role=MessageRole.USER, content="Hello BUDDY")]

    async def test_mock_provider_success(self) -> None:
        """Verify MockAIProvider returns structured AIResponse."""
        resp = await self.mock_provider.generate(self.messages)
        self.assertEqual(resp.provider, "mock")
        self.assertEqual(resp.model, "mock-v1")
        self.assertIn("BUDDY", resp.content)
        self.assertEqual(self.mock_provider.call_count, 1)

    async def test_mock_provider_custom_responses(self) -> None:
        """Verify MockAIProvider contextual replies."""
        resp_calc = await self.mock_provider.generate(
            [ChatMessage(role=MessageRole.USER, content="What is 25 * 4?")]
        )
        self.assertIn("100", resp_calc.content)

        resp_joke = await self.mock_provider.generate(
            [ChatMessage(role=MessageRole.USER, content="Tell me a short joke")]
        )
        self.assertIn("Windows", resp_joke.content)

    async def test_mock_provider_streaming(self) -> None:
        """Verify MockAIProvider generates streamed chunks."""
        chunks = []
        async for chunk in self.mock_provider.generate_stream(self.messages):
            chunks.append(chunk)

        full_text = "".join(chunks)
        self.assertIn("BUDDY", full_text)
        self.assertGreater(len(chunks), 1)

    async def test_mock_provider_simulated_failure(self) -> None:
        """Verify simulated failure raises AIProviderError."""
        self.mock_provider.simulate_failure = True
        with self.assertRaises(AIProviderError):
            await self.mock_provider.generate(self.messages)

    async def test_cloud_provider_missing_key_raises_auth_error(self) -> None:
        """Verify CloudAIProvider without API key raises AIAuthenticationError."""
        cloud = CloudAIProvider(api_key=None)
        with self.assertRaises(AIAuthenticationError):
            await cloud.generate(self.messages)

    @patch("httpx.AsyncClient.post")
    async def test_cloud_provider_success(self, mock_post) -> None:
        """Verify CloudAIProvider handles successful API response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "model": "gpt-4o-mini",
            "choices": [{"message": {"content": "I am BUDDY."}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        mock_post.return_value = mock_response

        cloud = CloudAIProvider(api_key="test-key", model="gpt-4o-mini")
        res = await cloud.generate(self.messages)

        self.assertEqual(res.content, "I am BUDDY.")
        self.assertEqual(res.provider, "cloud")
        self.assertEqual(res.model, "gpt-4o-mini")
        self.assertEqual(res.usage["total_tokens"], 15)

    @patch("httpx.AsyncClient.post")
    async def test_cloud_provider_auth_error(self, mock_post) -> None:
        """Verify 401 returns AIAuthenticationError without retrying."""
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "Invalid API key"
        mock_post.return_value = mock_resp

        cloud = CloudAIProvider(api_key="bad-key", max_retries=2)
        with self.assertRaises(AIAuthenticationError):
            await cloud.generate(self.messages)
        # Auth error must fail immediately without retrying
        self.assertEqual(mock_post.call_count, 1)

    @patch("httpx.AsyncClient.post")
    async def test_cloud_provider_rate_limit_retry(self, mock_post) -> None:
        """Verify 429 triggers retry and raises AIRateLimitError when exceeded."""
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {"Retry-After": "0.01"}
        mock_resp.text = "Rate limit reached"
        mock_post.return_value = mock_resp

        cloud = CloudAIProvider(api_key="key", max_retries=1, timeout=5.0)
        with self.assertRaises(AIRateLimitError):
            await cloud.generate(self.messages)
        self.assertEqual(mock_post.call_count, 2)

    @patch("httpx.AsyncClient.post")
    async def test_cloud_provider_timeout_error(self, mock_post) -> None:
        """Verify httpx.TimeoutException maps to AITimeoutError."""
        mock_post.side_effect = httpx.TimeoutException("Read timed out")

        cloud = CloudAIProvider(api_key="key", max_retries=1, timeout=0.1)
        with self.assertRaises(AITimeoutError):
            await cloud.generate(self.messages)

    async def test_local_provider_connection_failure(self) -> None:
        """Verify LocalAIProvider raises clean error when local service is unavailable."""
        local = LocalAIProvider(base_url="http://127.0.0.1:59999", timeout=0.5)
        with self.assertRaises(AIProviderError) as ctx:
            await local.generate(self.messages)
        self.assertIn("Local AI provider unavailable", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
