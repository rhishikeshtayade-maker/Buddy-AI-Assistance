"""BUDDY Agent Task Executor.

Orchestrates sequential, adaptive, and empirically verified multi-step execution.
Enforces per-step permission evaluation, user confirmation boundaries, dependency trees,
bounded retries, dynamic re-planning, and human cancellation controls.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app.agent.context import TaskContext
from app.agent.events import (
    TaskAuthenticationRequiredEvent,
    TaskCancelledEvent,
    TaskCompletedEvent,
    TaskConfirmationRequiredEvent,
    TaskExecutionStartedEvent,
    TaskFailedEvent,
    TaskPausedEvent,
    TaskReplannedEvent,
    TaskResumedEvent,
    TaskStepCompletedEvent,
    TaskStepFailedEvent,
    TaskStepStartedEvent,
)
from app.agent.models import (
    FailureCategory,
    StepStatus,
    Task,
    TaskResult,
    TaskStatus,
    TaskStep,
)
from app.agent.policies import (
    classify_failure,
    should_replan,
    should_retry,
)
from app.core.events import EventBus
from app.tools.executor import ToolExecutor
from app.tools.models import ToolExecutionStatus, ToolRequest, ToolResult

logger = logging.getLogger("buddy.agent.executor")


class TaskExecutor:
    """Coordinates the end-to-end execution of a validated Task."""

    def __init__(
        self,
        tool_executor: ToolExecutor,
        event_bus: Optional[EventBus] = None,
        context: Optional[TaskContext] = None,
    ) -> None:
        self._tool_executor = tool_executor
        self._event_bus = event_bus
        self._context = context
        self._cancelled_tasks: set[str] = set()

    def cancel_task(self, task: Task, reason: str = "User cancelled task") -> None:
        """Immediately stop scheduling future steps for this task."""
        self._cancelled_tasks.add(task.task_id)
        task.status = TaskStatus.CANCELLED
        logger.info("Task '%s' cancelled: %s", task.task_id, reason)

    def pause_task(self, task: Task, reason: str = "Task paused") -> None:
        """Pause task execution."""
        task.status = TaskStatus.PAUSED
        logger.info("Task '%s' paused: %s", task.task_id, reason)

    async def execute_task(
        self,
        task: Task,
        context: Optional[TaskContext] = None,
        confirmation_token: Optional[str] = None,
        auth_credential: Optional[str] = None,
    ) -> TaskResult:
        """Execute all steps of the task through the secure tool execution pipeline.

        Returns:
            TaskResult detailing verified outcomes, latency, and completed step IDs.
        """
        start_time = time.perf_counter()
        ctx = context or self._context or TaskContext(task_id=task.task_id, user_goal=task.user_goal)

        # Check if resumed from pause / waiting status
        is_resumed = task.status in (
            TaskStatus.PAUSED,
            TaskStatus.WAITING_CONFIRMATION,
            TaskStatus.WAITING_AUTHENTICATION,
        )

        task.status = TaskStatus.EXECUTING
        task.updated_at = time.time()

        if self._event_bus:
            if is_resumed:
                curr_id = task.current_step.step_id if task.current_step else None
                await self._event_bus.publish(TaskResumedEvent(task_id=task.task_id, step_id=curr_id))
            else:
                await self._event_bus.publish(
                    TaskExecutionStartedEvent(task_id=task.task_id, total_steps=len(task.steps))
                )

        completed_step_ids: List[str] = [
            s.step_id for s in task.steps if s.status == StepStatus.SUCCEEDED
        ]

        while task.current_step_index < len(task.steps):
            # 1. Human Cancellation Check
            if task.task_id in self._cancelled_tasks or task.status == TaskStatus.CANCELLED:
                task.status = TaskStatus.CANCELLED
                if self._event_bus:
                    await self._event_bus.publish(
                        TaskCancelledEvent(task_id=task.task_id, reason="User cancelled task")
                    )
                return TaskResult(
                    task_id=task.task_id,
                    status=TaskStatus.CANCELLED,
                    completed_steps=completed_step_ids,
                    final_message="Task was cancelled by user.",
                    verified=False,
                    execution_latency=time.perf_counter() - start_time,
                    tool_calls_count=task.tool_calls_count,
                )

            # 2. Infinite Loop & Tool Storm Protection
            if task.tool_calls_count >= task.max_tool_calls:
                err_msg = f"Task aborted: exceeded maximum tool calls limit ({task.max_tool_calls})."
                logger.error(err_msg)
                task.status = TaskStatus.FAILED
                if self._event_bus:
                    await self._event_bus.publish(
                        TaskFailedEvent(
                            task_id=task.task_id,
                            reason=err_msg,
                            category=FailureCategory.SECURITY_BLOCKED,
                        )
                    )
                return TaskResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    completed_steps=completed_step_ids,
                    final_message=err_msg,
                    verified=False,
                    execution_latency=time.perf_counter() - start_time,
                    tool_calls_count=task.tool_calls_count,
                )

            step = task.steps[task.current_step_index]

            # 3. Dependency Validation
            if not self._check_dependencies(step, completed_step_ids):
                step.status = StepStatus.SKIPPED
                step.failure_category = FailureCategory.DEPENDENCY_FAILED
                step.error = f"Prerequisite step(s) {step.dependencies} were not completed successfully."
                logger.warning("Step %s skipped due to failed dependencies.", step.step_id)
                # Advance past skipped step
                task.current_step_index += 1
                continue

            # 4. Execute Step with Retries & Gating
            step_result = await self._execute_step(
                task=task,
                step=step,
                context=ctx,
                confirmation_token=confirmation_token,
                auth_credential=auth_credential,
            )

            # Clear one-time tokens after first attempt
            confirmation_token = None
            auth_credential = None

            # Handle Waiting States (Confirmation / Authentication)
            if step_result.status == ToolExecutionStatus.CONFIRMATION_REQUIRED:
                task.status = TaskStatus.WAITING_CONFIRMATION
                token = step_result.metadata.get("confirmation_token", "")
                step.metadata["pending_request_id"] = step_result.request_id
                if self._event_bus:
                    await self._event_bus.publish(
                        TaskConfirmationRequiredEvent(
                            task_id=task.task_id,
                            step_id=step.step_id,
                            tool_name=step.tool_name,
                            risk_level=step.risk_level,
                            confirmation_token=token,
                            description=step.description,
                        )
                    )
                    await self._event_bus.publish(
                        TaskPausedEvent(
                            task_id=task.task_id,
                            reason=f"Awaiting user confirmation for step '{step.description}'",
                            waiting_status=TaskStatus.WAITING_CONFIRMATION,
                        )
                    )
                return TaskResult(
                    task_id=task.task_id,
                    status=TaskStatus.WAITING_CONFIRMATION,
                    completed_steps=completed_step_ids,
                    final_message=f"Confirmation required for: {step.description}",
                    verified=False,
                    execution_latency=time.perf_counter() - start_time,
                    tool_calls_count=task.tool_calls_count,
                    metadata={"confirmation_token": token, "pending_step_id": step.step_id},
                )

            if step_result.status == ToolExecutionStatus.AUTHENTICATION_REQUIRED:
                task.status = TaskStatus.WAITING_AUTHENTICATION
                if self._event_bus:
                    await self._event_bus.publish(
                        TaskAuthenticationRequiredEvent(
                            task_id=task.task_id,
                            step_id=step.step_id,
                            tool_name=step.tool_name,
                            risk_level=step.risk_level,
                            challenge=f"Authentication required to execute '{step.tool_name}'",
                        )
                    )
                    await self._event_bus.publish(
                        TaskPausedEvent(
                            task_id=task.task_id,
                            reason=f"Awaiting authentication for step '{step.description}'",
                            waiting_status=TaskStatus.WAITING_AUTHENTICATION,
                        )
                    )
                return TaskResult(
                    task_id=task.task_id,
                    status=TaskStatus.WAITING_AUTHENTICATION,
                    completed_steps=completed_step_ids,
                    final_message=f"Authentication required for: {step.description}",
                    verified=False,
                    execution_latency=time.perf_counter() - start_time,
                    tool_calls_count=task.tool_calls_count,
                    metadata={"pending_step_id": step.step_id},
                )

            # Step Outcome Evaluation
            if step_result.success and step_result.verified:
                step.status = StepStatus.SUCCEEDED
                step.result = step_result
                step.completed_at = time.time()
                completed_step_ids.append(step.step_id)
                ctx.record_step_result(step.step_id, step.tool_name, step_result)

                if self._event_bus:
                    await self._event_bus.publish(
                        TaskStepCompletedEvent(
                            task_id=task.task_id,
                            step_id=step.step_id,
                            tool_name=step.tool_name,
                            verified=True,
                            latency=step_result.execution_latency,
                        )
                    )

                task.current_step_index += 1
            else:
                # Step Failed or Verification Failed
                failure_cat = classify_failure(step_result.error, step_result.status)
                step.failure_category = failure_cat
                step.error = step_result.error

                # Check Re-planning condition
                if should_replan(failure_cat, task.replan_count, task.max_replans):
                    task.replan_count += 1
                    logger.info("Triggering re-plan for task %s (reason: %s)", task.task_id, failure_cat.name)
                    if self._event_bus:
                        await self._event_bus.publish(
                            TaskReplannedEvent(
                                task_id=task.task_id,
                                replan_count=task.replan_count,
                                reason=f"Environment changed or target missing: {failure_cat.name}",
                                new_step_count=len(task.steps),
                            )
                        )
                    # For re-plan attempt: retry step once with updated state
                    step.retries_attempted += 1
                    continue

                # Terminal Failure for this step
                step.status = StepStatus.FAILED
                task.status = TaskStatus.FAILED
                if self._event_bus:
                    await self._event_bus.publish(
                        TaskStepFailedEvent(
                            task_id=task.task_id,
                            step_id=step.step_id,
                            tool_name=step.tool_name,
                            category=failure_cat,
                            error=step_result.error or "Step failed",
                            will_retry=False,
                        )
                    )
                    await self._event_bus.publish(
                        TaskFailedEvent(
                            task_id=task.task_id,
                            failed_step_id=step.step_id,
                            reason=step_result.error or f"Step {step.step_id} failed",
                            category=failure_cat,
                        )
                    )

                return TaskResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    completed_steps=completed_step_ids,
                    failed_step=step.step_id,
                    final_message=f"Step '{step.description}' failed: {step_result.error}",
                    verified=False,
                    execution_latency=time.perf_counter() - start_time,
                    tool_calls_count=task.tool_calls_count,
                )

        # All steps completed successfully
        task.status = TaskStatus.COMPLETED
        total_lat = time.perf_counter() - start_time
        if self._event_bus:
            await self._event_bus.publish(
                TaskCompletedEvent(
                    task_id=task.task_id,
                    completed_steps=len(completed_step_ids),
                    total_latency=total_lat,
                )
            )

        return TaskResult(
            task_id=task.task_id,
            status=TaskStatus.COMPLETED,
            completed_steps=completed_step_ids,
            final_message=f"All {len(completed_step_ids)} steps completed and empirically verified.",
            verified=True,
            execution_latency=total_lat,
            tool_calls_count=task.tool_calls_count,
        )

    def _check_dependencies(self, step: TaskStep, completed_ids: List[str]) -> bool:
        """Verify that all prerequisite step IDs have finished with SUCCEEDED status."""
        for dep in step.dependencies:
            if dep not in completed_ids:
                return False
        return True

    async def _execute_step(
        self,
        task: Task,
        step: TaskStep,
        context: TaskContext,
        confirmation_token: Optional[str],
        auth_credential: Optional[str],
    ) -> ToolResult:
        """Execute a single step, handling bounded retries for transient failures."""
        step.status = StepStatus.EXECUTING
        step.started_at = time.time()

        if self._event_bus:
            await self._event_bus.publish(
                TaskStepStartedEvent(
                    task_id=task.task_id,
                    step_id=step.step_id,
                    sequence=step.sequence,
                    tool_name=step.tool_name,
                    description=step.description,
                )
            )

        # Prepare ToolRequest (reuse pending_request_id if resuming with confirmation token)
        pending_req_id = step.metadata.pop("pending_request_id", None) if confirmation_token else None
        req_kwargs: Dict[str, Any] = {
            "tool_name": step.tool_name,
            "arguments": dict(step.arguments),
            "conversation_id": task.conversation_id,
            "reason": step.description,
        }
        if pending_req_id:
            req_kwargs["request_id"] = pending_req_id

        tool_req = ToolRequest(**req_kwargs)

        while True:
            task.tool_calls_count += 1
            result = await self._tool_executor.execute(
                request=tool_req,
                confirmation_token=confirmation_token,
                auth_credential=auth_credential,
            )

            # If waiting for confirmation or authentication, return immediately
            if result.status in (
                ToolExecutionStatus.CONFIRMATION_REQUIRED,
                ToolExecutionStatus.AUTHENTICATION_REQUIRED,
            ):
                return result

            # If successful and verified, return
            if result.success and result.verified:
                return result

            # Failure branch: check bounded retry policy
            failure_cat = classify_failure(result.error, result.status)
            if should_retry(failure_cat, step.retries_attempted, step.retry_policy):
                step.retries_attempted += 1
                logger.info(
                    "Retrying step %s (attempt %d/%d, delay %.1fs)...",
                    step.step_id,
                    step.retries_attempted,
                    step.retry_policy.max_retries,
                    step.retry_policy.retry_delay_seconds,
                )
                if self._event_bus:
                    await self._event_bus.publish(
                        TaskStepFailedEvent(
                            task_id=task.task_id,
                            step_id=step.step_id,
                            tool_name=step.tool_name,
                            category=failure_cat,
                            error=result.error or "Transient error",
                            will_retry=True,
                        )
                    )
                await asyncio.sleep(step.retry_policy.retry_delay_seconds)
                continue

            # Non-retryable failure
            return result
