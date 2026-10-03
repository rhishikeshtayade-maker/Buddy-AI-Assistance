"""BUDDY Agent Subsystem (Loop 7).

Provides advanced agentic task planning, plan validation, dependency graph checks,
adaptive step execution, bounded retries, and strict security isolation.
"""

from app.agent.context import TaskContext
from app.agent.events import (
    TaskAuthenticationRequiredEvent,
    TaskCancelledEvent,
    TaskCompletedEvent,
    TaskConfirmationRequiredEvent,
    TaskCreatedEvent,
    TaskExecutionStartedEvent,
    TaskFailedEvent,
    TaskPausedEvent,
    TaskPlanCreatedEvent,
    TaskPlanningStartedEvent,
    TaskPlanRejectedEvent,
    TaskReplannedEvent,
    TaskResumedEvent,
    TaskStepCompletedEvent,
    TaskStepFailedEvent,
    TaskStepStartedEvent,
)
from app.agent.executor import TaskExecutor
from app.agent.models import (
    FailureCategory,
    RetryPolicy,
    StepStatus,
    Task,
    TaskResult,
    TaskStatus,
    TaskStep,
)
from app.agent.planner import TaskPlanner
from app.agent.policies import (
    classify_failure,
    is_forbidden_tool,
    should_replan,
    should_retry,
)
from app.agent.service import AgentService
from app.agent.validator import (
    PlanSecurityViolationError,
    PlanValidationError,
    TaskPlanValidator,
)

__all__ = [
    # Models & Statuses
    "Task",
    "TaskStep",
    "TaskStatus",
    "StepStatus",
    "TaskResult",
    "RetryPolicy",
    "FailureCategory",
    # Core Components
    "TaskPlanner",
    "TaskPlanValidator",
    "TaskExecutor",
    "TaskContext",
    "AgentService",
    # Exceptions
    "PlanValidationError",
    "PlanSecurityViolationError",
    # Policy Functions
    "classify_failure",
    "should_retry",
    "should_replan",
    "is_forbidden_tool",
    # Events
    "TaskCreatedEvent",
    "TaskPlanningStartedEvent",
    "TaskPlanCreatedEvent",
    "TaskPlanRejectedEvent",
    "TaskExecutionStartedEvent",
    "TaskStepStartedEvent",
    "TaskStepCompletedEvent",
    "TaskStepFailedEvent",
    "TaskConfirmationRequiredEvent",
    "TaskAuthenticationRequiredEvent",
    "TaskPausedEvent",
    "TaskResumedEvent",
    "TaskReplannedEvent",
    "TaskCompletedEvent",
    "TaskFailedEvent",
    "TaskCancelledEvent",
]
