"""BUDDY Advanced Reasoning and Long-Horizon Agent Orchestration (Loop 12).

Provides strongly typed goal representations, ambiguity detection, DAG planning,
empirical quality evaluation, explainable confidence, bounded failure diagnostics,
safe replanning, milestone/checkpoint tracking, and specialist roles.
"""

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
    Checkpoint,
    ClarificationRequest,
    ConfidenceAssessment,
    ConfidenceLevel,
    FailureDiagnosis,
    Goal,
    GoalAssumption,
    GoalConstraint,
    GoalPriority,
    GoalRequirement,
    GoalStatus,
    Milestone,
    ReasoningFailureCategory,
    StepEvaluationCategory,
    StepEvaluationResult,
    SubGoal,
    TaskBudget,
)
from app.agent.reasoning.orchestrator import LongHorizonOrchestrator
from app.agent.reasoning.parallel import SafeParallelCoordinator
from app.agent.reasoning.planner import LongHorizonPlanner
from app.agent.reasoning.replanner import SafeReplanner

__all__ = [
    # Models
    "Goal",
    "GoalStatus",
    "GoalPriority",
    "AutonomyLevel",
    "ConfidenceLevel",
    "ConfidenceAssessment",
    "GoalRequirement",
    "GoalConstraint",
    "GoalAssumption",
    "ClarificationRequest",
    "SubGoal",
    "Milestone",
    "Checkpoint",
    "TaskBudget",
    "FailureDiagnosis",
    "ReasoningFailureCategory",
    "StepEvaluationCategory",
    "StepEvaluationResult",
    # Subsystems
    "GoalRequirementExtractor",
    "AmbiguityDetector",
    "LongHorizonPlanner",
    "PlanQualityEvaluator",
    "ConfidenceEvaluator",
    "MilestoneManager",
    "FailureDiagnostician",
    "SafeReplanner",
    "SafeParallelCoordinator",
    "LongHorizonOrchestrator",
    # Events
    "GoalCreatedEvent",
    "RequirementsExtractedEvent",
    "ClarificationRequestedEvent",
    "PlanCreatedEvent",
    "PlanValidatedEvent",
    "PlanRejectedEvent",
    "MilestoneStartedEvent",
    "MilestoneCompletedEvent",
    "CheckpointCreatedEvent",
    "StepEvaluatedEvent",
    "FailureDiagnosedEvent",
    "ReplanStartedEvent",
    "ReplanCompletedEvent",
    "ConfidenceEvaluatedEvent",
    "BudgetExceededEvent",
    "GoalCompletedEvent",
    "GoalFailedEvent",
    "GoalCancelledEvent",
]
