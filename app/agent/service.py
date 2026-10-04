"""BUDDY Agent Service.

High-level orchestrator connecting TaskPlanner, TaskPlanValidator, TaskExecutor,
StateMachine, and EventBus into a cohesive, secure agentic workflow.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from app.agent.context import TaskContext
from app.agent.executor import TaskExecutor
from app.agent.models import Task, TaskResult, TaskStatus
from app.agent.planner import TaskPlanner
from app.agent.validator import TaskPlanValidator
from app.ai.provider import AIProvider
from app.core.events import EventBus
from app.core.state import BuddyState, StateMachine
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry

logger = logging.getLogger("buddy.agent.service")


class AgentService:
    """Unified entrypoint for planning, validating, and executing agentic tasks."""

    def __init__(
        self,
        registry: ToolRegistry,
        tool_executor: ToolExecutor,
        ai_provider: Optional[AIProvider] = None,
        event_bus: Optional[EventBus] = None,
        state_machine: Optional[StateMachine] = None,
        max_steps: int = 20,
        memory_manager: Optional[Any] = None,
    ) -> None:
        self._registry = registry
        self._tool_executor = tool_executor
        self._ai_provider = ai_provider
        self._event_bus = event_bus
        self._state_machine = state_machine
        self._memory_manager = memory_manager

        self._validator = TaskPlanValidator(registry, max_steps=max_steps)
        self._planner = TaskPlanner(
            registry=registry,
            ai_provider=ai_provider,
            validator=self._validator,
            event_bus=event_bus,
            max_steps=max_steps,
        )
        self._executor = TaskExecutor(
            tool_executor=tool_executor,
            event_bus=event_bus,
        )

        from app.agent.reasoning.orchestrator import LongHorizonOrchestrator
        self._long_horizon = LongHorizonOrchestrator(
            registry=registry,
            tool_executor=tool_executor,
            ai_provider=ai_provider,
            event_bus=event_bus,
            memory_manager=memory_manager,
        )

        self._tasks: Dict[str, Task] = {}
        self._contexts: Dict[str, TaskContext] = {}

    @property
    def long_horizon_orchestrator(self) -> Any:
        return self._long_horizon

    @property
    def memory_manager(self) -> Optional[Any]:
        return self._memory_manager

    def set_memory_manager(self, manager: Any) -> None:
        self._memory_manager = manager

    @property
    def planner(self) -> TaskPlanner:
        return self._planner

    @property
    def validator(self) -> TaskPlanValidator:
        return self._validator

    @property
    def executor(self) -> TaskExecutor:
        return self._executor

    def get_task(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def list_active_tasks(self) -> List[Task]:
        return [
            t for t in self._tasks.values()
            if t.status in (TaskStatus.EXECUTING, TaskStatus.WAITING_CONFIRMATION, TaskStatus.WAITING_AUTHENTICATION, TaskStatus.PAUSED)
        ]

    def cancel_task(self, task_id: str, reason: str = "User cancelled task") -> bool:
        task = self._tasks.get(task_id)
        if not task:
            return False
        self._executor.cancel_task(task, reason=reason)
        return True

    async def submit_goal(
        self,
        user_goal: str,
        conversation_id: Optional[str] = None,
    ) -> Task:
        """Decompose a goal into a validated Task without executing it."""
        # 1. State Machine: Transition to THINKING
        if self._state_machine and self._state_machine.can_transition_to(BuddyState.THINKING):
            self._state_machine.transition_to(
                BuddyState.THINKING,
                reason="Planning agentic task",
            )

        # 2. Recall contextual user preferences from memory if available
        user_prefs: List[str] = []
        if self._memory_manager:
            try:
                mems = await self._memory_manager.recall(user_goal, limit=5)
                user_prefs = [m.content for m in mems]
            except Exception as e:
                logger.warning("Failed to recall user preferences for goal: %s", e)

        ctx = TaskContext(
            task_id="provisional",
            user_goal=user_goal,
            conversation_id=conversation_id,
            user_preferences=user_prefs,
        )

        task = await self._planner.plan(
            user_goal=user_goal,
            context=ctx,
            conversation_id=conversation_id,
        )
        ctx.task_id = task.task_id
        self._tasks[task.task_id] = task
        self._contexts[task.task_id] = ctx

        # Return to IDLE after planning if not executing immediately
        if self._state_machine and self._state_machine.can_transition_to(BuddyState.IDLE):
            self._state_machine.transition_to(
                BuddyState.IDLE,
                reason="Task plan created and ready",
            )

        return task

    async def execute_goal(
        self,
        user_goal: str,
        confirmation_token: Optional[str] = None,
        auth_credential: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> TaskResult:
        """Plan, validate, and execute a multi-step user goal end-to-end."""
        # 1. Plan goal
        task = await self.submit_goal(user_goal=user_goal, conversation_id=conversation_id)

        # 2. State Machine: Transition to EXECUTING
        if self._state_machine and self._state_machine.can_transition_to(BuddyState.EXECUTING):
            self._state_machine.transition_to(
                BuddyState.EXECUTING,
                reason="Executing agentic task plan",
            )

        # 3. Execute
        ctx = self._contexts[task.task_id]
        result = await self._executor.execute_task(
            task=task,
            context=ctx,
            confirmation_token=confirmation_token,
            auth_credential=auth_credential,
        )

        # 4. State Machine Transition post-execution
        if result.status == TaskStatus.COMPLETED:
            if self._state_machine and self._state_machine.can_transition_to(BuddyState.THINKING):
                self._state_machine.transition_to(BuddyState.THINKING, reason="Task completed, synthesizing response")
            if self._state_machine and self._state_machine.can_transition_to(BuddyState.IDLE):
                self._state_machine.transition_to(BuddyState.IDLE, reason="Task finished")
        elif result.status in (TaskStatus.WAITING_CONFIRMATION, TaskStatus.WAITING_AUTHENTICATION, TaskStatus.PAUSED):
            if self._state_machine and self._state_machine.can_transition_to(BuddyState.IDLE):
                self._state_machine.transition_to(BuddyState.IDLE, reason="Waiting for user input/confirmation")

        return result

    async def resume_task(
        self,
        task_id: str,
        confirmation_token: Optional[str] = None,
        auth_credential: Optional[str] = None,
    ) -> TaskResult:
        """Resume execution of a paused or waiting task with user-supplied credentials/tokens."""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task with ID '{task_id}' not found.")

        ctx = self._contexts.get(task_id) or TaskContext(task_id=task.task_id, user_goal=task.user_goal)

        if self._state_machine and self._state_machine.can_transition_to(BuddyState.EXECUTING):
            self._state_machine.transition_to(BuddyState.EXECUTING, reason="Resuming agentic task execution")

        result = await self._executor.execute_task(
            task=task,
            context=ctx,
            confirmation_token=confirmation_token,
            auth_credential=auth_credential,
        )

        if result.status == TaskStatus.COMPLETED:
            if self._state_machine and self._state_machine.can_transition_to(BuddyState.IDLE):
                self._state_machine.transition_to(BuddyState.IDLE, reason="Resumed task completed")
        elif result.status in (TaskStatus.WAITING_CONFIRMATION, TaskStatus.WAITING_AUTHENTICATION, TaskStatus.PAUSED):
            if self._state_machine and self._state_machine.can_transition_to(BuddyState.IDLE):
                self._state_machine.transition_to(BuddyState.IDLE, reason="Waiting for user input/confirmation")

        return result

    async def submit_long_horizon_goal(
        self,
        objective: str,
        conversation_id: Optional[str] = None,
        autonomy_level: Optional[Any] = None,
        detected_candidates: Optional[List[str]] = None,
    ) -> Any:
        """Submit a long-horizon Goal through the reasoning engine."""
        return await self._long_horizon.submit_goal(
            objective=objective,
            conversation_id=conversation_id,
            autonomy_level=autonomy_level,
            detected_candidates=detected_candidates,
        )

    async def execute_long_horizon_goal(
        self,
        goal_id: str,
        confirmation_token: Optional[str] = None,
        auth_credential: Optional[str] = None,
    ) -> Any:
        """Execute all planned steps of a long-horizon goal with empirical verification."""
        return await self._long_horizon.execute_goal(
            goal_id=goal_id,
            confirmation_token=confirmation_token,
            auth_credential=auth_credential,
        )

    def cancel_long_horizon_goal(self, goal_id: str, reason: str = "User cancelled goal") -> bool:
        """Cancel a long-horizon goal idempotently."""
        return self._long_horizon.cancel_goal(goal_id=goal_id, reason=reason)
