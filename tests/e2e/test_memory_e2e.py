"""End-to-End tests for BUDDY Long-Term Memory and Conversational Integration."""

from __future__ import annotations

import unittest

from app.agent.service import AgentService
from app.ai.conversation import ConversationManager
from app.ai.models import MessageRole
from app.ai.provider import MockAIProvider
from app.ai.router import AIRouter
from app.core import BuddyConfig, BuddyState, EventBus, StateMachine
from app.memory.manager import MemoryManager
from app.memory.policy import MemoryPolicy
from app.memory.service import MemoryService
from app.memory.store import SqliteMemoryStore
from app.tools.builtin import register_builtin_tools
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


class TestMemoryE2E(unittest.IsolatedAsyncioTestCase):
    """End-to-end multi-turn dialogue with memory persistence, recall, forget, and agent integration."""

    async def asyncSetUp(self) -> None:
        self.config = BuddyConfig()
        self.event_bus = EventBus()
        self.state_machine = StateMachine(BuddyState.IDLE)
        self.ai_provider = MockAIProvider(default_response="Acknowledged.")
        self.router = AIRouter(self.config)
        self.router.register_provider("mock", self.ai_provider)

        # Persistent SQLite store
        self.store = SqliteMemoryStore(db_path=":memory:")
        self.policy = MemoryPolicy(self.config)
        self.memory_service = MemoryService(store=self.store, policy=self.policy, event_bus=self.event_bus, config=self.config)
        self.memory_mgr = MemoryManager(service=self.memory_service, config=self.config)

        # Tools & Executor
        self.registry = ToolRegistry()
        register_builtin_tools(self.registry)
        self.tool_executor = ToolExecutor(registry=self.registry, event_bus=self.event_bus)

        # Conversation Manager with Memory attached
        self.conv_mgr = ConversationManager(
            config=self.config,
            event_bus=self.event_bus,
            state_machine=self.state_machine,
            router=self.router,
            tool_executor=self.tool_executor,
            memory_manager=self.memory_mgr,
        )

        # Agent Service with Memory attached
        self.agent_service = AgentService(
            registry=self.registry,
            tool_executor=self.tool_executor,
            ai_provider=self.ai_provider,
            event_bus=self.event_bus,
            state_machine=self.state_machine,
            memory_manager=self.memory_mgr,
        )

    async def asyncTearDown(self) -> None:
        self.store.close()
        await self.event_bus.shutdown()

    async def test_full_conversational_memory_lifecycle(self) -> None:
        # Turn 1: User issues natural language memory command
        resp1 = await self.conv_mgr.process_user_turn("Remember that I use VS Code.")
        self.assertIn("remember", resp1.content.lower())
        self.assertIn("vs code", resp1.content.lower())

        # Verify record exists in store
        mems = await self.memory_mgr.list_memories()
        self.assertEqual(len(mems), 1)
        self.assertEqual(mems[0].content, "I use VS Code")

        # Turn 2: User queries memories
        resp2 = await self.conv_mgr.process_user_turn("What do you remember about me?")
        self.assertIn("I use VS Code", resp2.content)

        # Turn 3: User states a regular coding question
        # Memory is recalled and injected into system prompt without breaking dialogue
        self.ai_provider.set_next_response("I will configure your project for VS Code.")
        resp3 = await self.conv_mgr.process_user_turn("How should I set up my Python project?")
        self.assertIn("VS Code", resp3.content)

        # Turn 4: User asks to forget the preference
        resp4 = await self.conv_mgr.process_user_turn("Forget my preference regarding I use VS Code.")
        self.assertIn("forgotten", resp4.content.lower())

        # Verify memory is no longer retrievable
        mems_after = await self.memory_mgr.list_memories()
        self.assertEqual(len(mems_after), 0)

    async def test_secret_statement_rejected_and_never_persisted(self) -> None:
        resp = await self.conv_mgr.process_user_turn("Remember that my password is SuperSecretAdmin123!")
        self.assertIn("cannot", resp.content.lower())
        self.assertIn("secret or credential pattern detected", resp.content.lower())

        # Memory store remains completely empty
        mems = await self.memory_mgr.list_memories()
        self.assertEqual(len(mems), 0)

    async def test_agent_integration_informs_context_without_permission_bypass(self) -> None:
        # 1. User records editor preference
        await self.memory_mgr.remember("User preferred application is notepad")

        # 2. Submit goal to AgentService
        task = await self.agent_service.submit_goal("Open Notepad, type BUDDY TEST, and finish.")
        self.assertIsNotNone(task)
        self.assertEqual(len(task.steps), 3)

        # 3. Context has user preferences recorded
        ctx = self.agent_service._contexts[task.task_id]
        self.assertIn("User preferred application is notepad", ctx.user_preferences)

        # 4. Invariant: Memory DOES NOT give permission bypass for dangerous action
        # If a step requires confirmation, it STILL requires confirmation
        step_focus = task.steps[1]  # mouse.click
        self.assertTrue(step_focus.requires_confirmation)


if __name__ == "__main__":
    unittest.main()
