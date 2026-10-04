"""BUDDY Long-Horizon Agent Orchestrator (Loop 12).

Orchestrates end-to-end long-horizon goal processing:
1. Intent & Requirement Analysis
2. Ambiguity Clarification Gate
3. DAG Planning with Milestones & Checkpoints
4. Plan Quality & Security Validation
5. Step Execution (Sequential & Safe Parallel) via ToolExecutor
6. Intermediate Result Evaluation & Empirical Verification
7. Failure Diagnosis & Bounded Safe Replanning
8. Budget Enforcement & Explainable Confidence Assessment
9. Full Audit Trail Integration
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app.agent.executor import TaskExecutor
from app.agent.models import StepStatus, Task, TaskResult, TaskStatus, TaskStep
from app.agent.reasoning.ambiguity import AmbiguityDetector
from app.agent.reasoning.confidence import ConfidenceEvaluator
from app.agent.reasoning.diagnostics import FailureDiagnostician
from app.agent.reasoning.evaluator import PlanQualityEvaluator
from app.agent.reasoning.events import (
    BudgetExceededEvent,
    CheckpointCreatedEvent,
    ClarificationRequestedEvent,
    ConfidenceEvaluatedEvent,
    FailureDiagnosedEvent,
    GoalCancelledEvent,
    GoalCompletedEvent,
    GoalCreatedEvent,
    GoalFailedEvent,
    MilestoneCompletedEvent,
    MilestoneStartedEvent,
    PlanCreatedEvent,
    PlanRejectedEvent,
    PlanValidatedEvent,
    ReplanCompletedEvent,
    ReplanStartedEvent,
    RequirementsExtractedEvent,
    StepEvaluatedEvent,
)
from app.agent.reasoning.extractor import GoalRequirementExtractor
from app.agent.reasoning.milestones import MilestoneManager
from app.agent.reasoning.models import (
    AutonomyLevel,
    ClarificationRequest,
    Goal,
    GoalStatus,
    StepEvaluationCategory,
    TaskBudget,
)
from app.agent.reasoning.parallel import SafeParallelCoordinator
from app.agent.reasoning.planner import LongHorizonPlanner
from app.agent.reasoning.replanner import SafeReplanner
from app.agent.validator import TaskPlanValidator
from app.ai.provider import AIProvider
from app.core.events import EventBus
from app.security.audit import AuditLogger, AuditRecord
from app.tools.executor import ToolExecutor
from app.tools.models import ToolRequest, ToolResult, ToolRiskLevel
from app.tools.registry import ToolRegistry

logger = logging.getLogger("buddy.agent.reasoning.orchestrator")


class LongHorizonOrchestrator:
    """Central engine coordinating long-horizon goal reasoning and verified execution."""

    def __init__(
        self,
        registry: ToolRegistry,
        tool_executor: ToolExecutor,
        ai_provider: Optional[AIProvider] = None,
        event_bus: Optional[EventBus] = None,
        audit_logger: Optional[AuditLogger] = None,
        memory_manager: Optional[Any] = None,
        context_service: Optional[Any] = None,
        default_autonomy: AutonomyLevel = AutonomyLevel.SUPERVISED,
    ) -> None:
        self._registry = registry
        self._tool_executor = tool_executor
        self._ai_provider = ai_provider
        self._event_bus = event_bus
        self._audit = audit_logger
        self._memory = memory_manager
        self._context = context_service
        self._autonomy = default_autonomy

        # Subsystems
        self._ambiguity_detector = AmbiguityDetector()
        self._extractor = GoalRequirementExtractor(self._ambiguity_detector)
        self._validator = TaskPlanValidator(registry)
        self._diagnostician = FailureDiagnostician()
        self._evaluator = PlanQualityEvaluator(registry, self._diagnostician)
        self._confidence = ConfidenceEvaluator()
        self._milestones = MilestoneManager()
        self._replanner = SafeReplanner(registry, self._evaluator, self._diagnostician)
        self._parallel = SafeParallelCoordinator(tool_executor)

        self._planner = LongHorizonPlanner(
            registry=registry,
            ai_provider=ai_provider,
            validator=self._validator,
            evaluator=self._evaluator,
            event_bus=event_bus,
        )

        self._goals: Dict[str, Goal] = {}
        self._cancelled_goals: set[str] = set()

    def get_goal(self, goal_id: str) -> Optional[Goal]:
        return self._goals.get(goal_id)

    async def submit_goal(
        self,
        objective: str,
        conversation_id: Optional[str] = None,
        autonomy_level: Optional[AutonomyLevel] = None,
        detected_candidates: Optional[List[str]] = None,
    ) -> Goal:
        """Analyze objective, extract requirements, check ambiguity, and create long-horizon Goal."""
        autonomy = autonomy_level or self._autonomy

        # Retrieve soft preferences from Memory if available (never authority)
        memory_prefs: List[str] = []
        if self._memory:
            try:
                # Query memory context safely
                recs = await self._memory.retrieve_relevant_memories(objective, limit=3)
                for r in recs:
                    if hasattr(r, "content"):
                        memory_prefs.append(r.content)
            except Exception:
                pass

        # 1. Requirement & Goal Extraction
        goal = self._extractor.extract_goal(
            objective=objective,
            conversation_id=conversation_id,
            memory_preferences=memory_prefs,
            detected_candidates=detected_candidates,
        )
        goal.autonomy_level = autonomy
        self._goals[goal.goal_id] = goal

        if self._event_bus:
            await self._event_bus.publish(
                GoalCreatedEvent(
                    goal_id=goal.goal_id,
                    objective=goal.objective,
                    priority=goal.priority.value,
                    conversation_id=goal.conversation_id,
                )
            )
            await self._event_bus.publish(
                RequirementsExtractedEvent(
                    goal_id=goal.goal_id,
                    requirement_count=len(goal.requirements),
                    constraint_count=len(goal.constraints),
                    assumption_count=len(goal.assumptions),
                    prohibited_count=len(goal.prohibited_actions),
                )
            )

        # 2. Check for blocking ambiguity
        if goal.pending_clarification and goal.pending_clarification.is_blocking:
            if self._event_bus:
                await self._event_bus.publish(
                    ClarificationRequestedEvent(
                        goal_id=goal.goal_id,
                        request_id=goal.pending_clarification.request_id,
                        question=goal.pending_clarification.question,
                        affected_requirement=goal.pending_clarification.affected_requirement,
                        is_blocking=True,
                    )
                )
            return goal

        # 3. Plan Generation
        try:
            task = await self._planner.create_long_horizon_plan(goal)
            if self._event_bus:
                await self._event_bus.publish(
                    PlanCreatedEvent(
                        goal_id=goal.goal_id,
                        task_id=task.task_id,
                        subgoal_count=len(goal.subgoals),
                        step_count=len(task.steps),
                        milestone_count=len(goal.milestones),
                    )
                )
                await self._event_bus.publish(
                    PlanValidatedEvent(
                        goal_id=goal.goal_id,
                        task_id=task.task_id,
                        step_count=len(task.steps),
                    )
                )
        except Exception as e:
            goal.status = GoalStatus.FAILED
            if self._event_bus:
                await self._event_bus.publish(
                    PlanRejectedEvent(
                        goal_id=goal.goal_id,
                        task_id="",
                        reason=str(e),
                    )
                )
            raise

        return goal

    async def resolve_clarification(
        self,
        goal_id: str,
        chosen_interpretation: str,
    ) -> Goal:
        """Resolve pending ambiguity with user input and resume planning."""
        goal = self._goals.get(goal_id)
        if not goal:
            raise ValueError(f"Goal '{goal_id}' not found.")

        if not goal.pending_clarification:
            return goal

        goal.pending_clarification.chosen_interpretation = chosen_interpretation
        goal.pending_clarification.answered = True
        goal.pending_clarification.is_blocking = False

        # Update objective with resolved target
        updated_obj = f"{goal.objective} (Target: {chosen_interpretation})"
        goal.objective = updated_obj

        # Plan with resolved goal
        await self._planner.create_long_horizon_plan(goal)
        return goal

    def cancel_goal(self, goal_id: str, reason: str = "User cancelled goal") -> bool:
        """Idempotently cancel a running or pending goal."""
        goal = self._goals.get(goal_id)
        if not goal:
            return False

        self._cancelled_goals.add(goal_id)
        goal.status = GoalStatus.CANCELLED
        if goal.task_plan:
            goal.task_plan.status = TaskStatus.CANCELLED

        logger.info("Goal '%s' cancelled: %s", goal_id, reason)
        if self._event_bus:
            self._event_bus.publish_sync(
                GoalCancelledEvent(goal_id=goal_id, reason=reason)
            )
        return True

    async def execute_goal(
        self,
        goal_id: str,
        confirmation_token: Optional[str] = None,
        auth_credential: Optional[str] = None,
    ) -> Goal:
        """Execute all steps of the planned goal with continuous verification and diagnostics."""
        goal = self._goals.get(goal_id)
        if not goal:
            raise ValueError(f"Goal '{goal_id}' not found.")

        if goal.status in (GoalStatus.WAITING_CLARIFICATION, GoalStatus.CANCELLED):
            return goal

        task = goal.task_plan
        if not task:
            raise ValueError(f"Goal '{goal_id}' has no task plan.")

        goal.status = GoalStatus.EXECUTING
        goal.budget.start()
        start_time = time.time()

        for idx, step in enumerate(task.steps):
            # Skip steps that already succeeded in previous execution / turns
            if step.status == StepStatus.SUCCEEDED:
                continue

            # 1. Cancellation check
            if goal_id in self._cancelled_goals or goal.status == GoalStatus.CANCELLED:
                goal.status = GoalStatus.CANCELLED
                task.status = TaskStatus.CANCELLED
                break

            # 2. Budget check
            exhausted, exhaust_reason = goal.budget.is_exhausted()
            if exhausted:
                goal.status = GoalStatus.BUDGET_EXCEEDED
                task.status = TaskStatus.BLOCKED
                if self._event_bus:
                    await self._event_bus.publish(
                        BudgetExceededEvent(
                            goal_id=goal.goal_id,
                            limit_name="task_budget",
                            current_value=float(goal.budget.current_steps),
                        )
                    )
                break

            task.current_step_index = idx
            goal.budget.record_step()

            # Execute single step through ToolExecutor
            step.status = StepStatus.EXECUTING
            req_id = f"step_{step.step_id}"
            tool_req = ToolRequest(
                request_id=req_id,
                tool_name=step.tool_name,
                arguments=step.arguments,
            )

            tool_res = await self._tool_executor.execute(
                request=tool_req,
                confirmation_token=confirmation_token,
                auth_credential=auth_credential,
            )
            step.result = tool_res

            # Audit record for step execution decision
            if self._audit:
                self._audit.record(
                    AuditRecord(
                        request_id=f"step_{step.step_id}",
                        tool_name=step.tool_name,
                        risk_level=step.risk_level.name,
                        permission_decision=tool_res.status.name,
                        execution_status=tool_res.status.name,
                        verified=tool_res.verified,
                        execution_latency=tool_res.execution_latency,
                        metadata={"goal_id": goal.goal_id, "step_id": step.step_id},
                    )
                )

            # 3. Intermediate Outcome Evaluation
            eval_res = self._evaluator.evaluate_step_result(step, tool_res)

            if self._event_bus:
                await self._event_bus.publish(
                    StepEvaluatedEvent(
                        goal_id=goal.goal_id,
                        step_id=step.step_id,
                        category=eval_res.category.value,
                        is_verified=eval_res.is_verified,
                        details=eval_res.actual_result or "",
                    )
                )

            # 4. Handle Step Outcome
            if eval_res.category == StepEvaluationCategory.SUCCESS:
                step.status = StepStatus.SUCCEEDED
                # Update milestones and record checkpoint
                chk = self._milestones.update_milestone_progress(goal, step.step_id, step_verified=True)
                if chk and self._event_bus:
                    await self._event_bus.publish(
                        CheckpointCreatedEvent(
                            goal_id=goal.goal_id,
                            checkpoint_id=chk.checkpoint_id,
                            milestone_id=chk.milestone_id,
                            completed_steps_count=len(chk.completed_step_ids),
                        )
                    )

            elif eval_res.category == StepEvaluationCategory.SECURITY_BLOCK:
                step.status = StepStatus.FAILED
                goal.status = GoalStatus.BLOCKED
                task.status = TaskStatus.BLOCKED
                logger.error("Step '%s' blocked by security policy.", step.step_id)
                break

            elif eval_res.category == StepEvaluationCategory.USER_REQUIRED:
                step.status = StepStatus.WAITING_CONFIRMATION
                goal.status = GoalStatus.WAITING_CONFIRMATION
                task.status = TaskStatus.WAITING_CONFIRMATION
                logger.info("Step '%s' paused for user confirmation/auth.", step.step_id)
                break

            elif eval_res.category == StepEvaluationCategory.RECOVERABLE_FAILURE:
                step.status = StepStatus.FAILED
                diag = eval_res.diagnostic
                if diag and diag.replannable and self._replanner.replan_failed_step(task, step, diag, goal):
                    if self._event_bus:
                        await self._event_bus.publish(
                            ReplanStartedEvent(
                                goal_id=goal.goal_id,
                                failed_step_id=step.step_id,
                                replan_count=task.replan_count,
                                reason=diag.message,
                            )
                        )
                        await self._event_bus.publish(
                            ReplanCompletedEvent(
                                goal_id=goal.goal_id,
                                replan_count=task.replan_count,
                                new_step_count=len(task.steps),
                            )
                        )
                    # Step replanned, continue executing from current index
                    continue
                else:
                    goal.status = GoalStatus.FAILED
                    task.status = TaskStatus.FAILED
                    break

            else:
                step.status = StepStatus.FAILED
                goal.status = GoalStatus.FAILED
                task.status = TaskStatus.FAILED
                break

        # Final Goal Outcome
        all_succeeded = all(s.status == StepStatus.SUCCEEDED for s in task.steps)
        duration = time.time() - start_time

        if all_succeeded and goal.status == GoalStatus.EXECUTING:
            goal.status = GoalStatus.COMPLETED
            task.status = TaskStatus.COMPLETED
            if self._event_bus:
                await self._event_bus.publish(
                    GoalCompletedEvent(
                        goal_id=goal.goal_id,
                        total_steps=len(task.steps),
                        duration_seconds=duration,
                        verified=True,
                    )
                )
        elif goal.status == GoalStatus.EXECUTING:
            goal.status = GoalStatus.FAILED
            task.status = TaskStatus.FAILED
            if self._event_bus:
                await self._event_bus.publish(
                    GoalFailedEvent(
                        goal_id=goal.goal_id,
                        reason="One or more steps failed during execution",
                    )
                )

        return goal
