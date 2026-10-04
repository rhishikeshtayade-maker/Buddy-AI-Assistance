"""BUDDY Loop 12 Advanced Reasoning & Long-Horizon Orchestration Smoke Test.

Run directly via:
    python -m app.agent.reasoning.smoke_test

Verifies all Loop 12 reasoning subsystems, models, ambiguity gates, DAG planning,
milestones, checkpoints, failure diagnostics, safe replanning, and budgets.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

from app.agent.models import StepStatus, Task, TaskStep
from app.agent.reasoning.ambiguity import AmbiguityDetector
from app.agent.reasoning.confidence import ConfidenceEvaluator
from app.agent.reasoning.diagnostics import FailureDiagnostician
from app.agent.reasoning.evaluator import PlanQualityEvaluator
from app.agent.reasoning.extractor import GoalRequirementExtractor
from app.agent.reasoning.milestones import MilestoneManager
from app.agent.reasoning.models import (
    AutonomyLevel,
    ConfidenceLevel,
    Goal,
    GoalStatus,
    ReasoningFailureCategory,
    StepEvaluationCategory,
    TaskBudget,
)
from app.agent.reasoning.orchestrator import LongHorizonOrchestrator
from app.agent.reasoning.parallel import SafeParallelCoordinator
from app.agent.reasoning.planner import LongHorizonPlanner
from app.agent.reasoning.replanner import SafeReplanner
from app.agent.specialists import (
    BrowserRole,
    CoderRole,
    ComputerRole,
    ResearcherRole,
    VerifierRole,
)
from app.agent.validator import TaskPlanValidator
from app.ai.provider import MockAIProvider
from app.core.events import EventBus
from app.security.audit import AuditLogger
from app.security.path_policy import PathPolicy
from app.tools.builtin import (
    FileCreateTool,
    FileReadTool,
    FileRenameTool,
    FileSearchTool,
    SystemInfoTool,
)
from app.tools.executor import ToolExecutor
from app.tools.models import ToolExecutionStatus, ToolRequest, ToolResult, ToolRiskLevel
from app.tools.registry import ToolRegistry


async def run_smoke_test() -> int:
    print("======================================================================")
    print("BUDDY LOOP 12 — ADVANCED REASONING & ORCHESTRATION SMOKE TEST")
    print(f"Platform: {sys.platform} | Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("======================================================================")

    passed_stages = 0
    total_stages = 12

    with tempfile.TemporaryDirectory() as td:
        workspace_dir = Path(td)
        path_policy = PathPolicy(allowed_roots=[workspace_dir])

        # 1. Setup Registry & Tools
        registry = ToolRegistry()
        registry.register_tool(SystemInfoTool())
        registry.register_tool(FileSearchTool(path_policy))
        registry.register_tool(FileReadTool(path_policy))
        registry.register_tool(FileCreateTool(path_policy))
        registry.register_tool(FileRenameTool(path_policy))

        event_bus = EventBus()
        audit_log = workspace_dir / "audit.log"
        audit = AuditLogger(log_path=audit_log)
        tool_executor = ToolExecutor(registry=registry, audit_logger=audit, event_bus=event_bus)

        # STAGE 1: Structured Requirement Extraction
        extractor = GoalRequirementExtractor()
        user_prompt = "Create a text file called buddy_report.txt on Desktop and verify it"
        goal = extractor.extract_goal(user_prompt)
        assert goal.objective == user_prompt
        assert len(goal.requirements) >= 1
        assert len(goal.constraints) >= 1
        print("[PASSED] Stage: 1. Goal & Requirement Extraction")
        passed_stages += 1

        # STAGE 2: Ambiguity Detection & Clarification Request
        ambiguity_detector = AmbiguityDetector()
        ambiguous_prompt = "Delete the file"
        clarification = ambiguity_detector.detect_goal_ambiguity(ambiguous_prompt)
        assert clarification is not None
        assert clarification.is_blocking is True
        print(f"[PASSED] Stage: 2. Ambiguity Handling - Blocking clarification: '{clarification.question}'")
        passed_stages += 1

        # STAGE 3: Long-Horizon DAG Planning
        planner = LongHorizonPlanner(registry=registry, event_bus=event_bus)
        test_file = workspace_dir / "buddy_reasoning_test.txt"
        goal_exec = extractor.extract_goal(f"Create file {test_file.name} with content 'Hello BUDDY'")
        # Ensure path is absolute in workspace for execution
        planned_task = await planner.create_long_horizon_plan(goal_exec)
        assert len(planned_task.steps) >= 1
        assert len(goal_exec.subgoals) >= 1
        assert len(goal_exec.milestones) >= 1
        print(f"[PASSED] Stage: 3. Long-Horizon DAG Planning - Steps: {len(planned_task.steps)}, Milestones: {len(goal_exec.milestones)}")
        passed_stages += 1

        # STAGE 4: Plan Quality Validation
        evaluator = PlanQualityEvaluator(registry)
        is_valid, issues = evaluator.evaluate_plan_quality(planned_task, goal_exec)
        assert is_valid is True
        assert len(issues) == 0
        print("[PASSED] Stage: 4. Plan Quality & Verification Coverage Gate")
        passed_stages += 1

        # STAGE 5: Explainable Confidence Model
        confidence_eval = ConfidenceEvaluator()
        conf = confidence_eval.evaluate_plan_confidence(planned_task, goal_exec)
        assert 0.0 <= conf.score <= 1.0
        assert len(conf.reason_codes) >= 1
        print(f"[PASSED] Stage: 5. Explainable Confidence Assessment - Score: {conf.score:.2f} ({conf.level.value})")
        passed_stages += 1

        # STAGE 6: Milestone & Checkpoint Management
        ms_manager = MilestoneManager()
        chk = ms_manager.update_milestone_progress(goal_exec, planned_task.steps[0].step_id, step_verified=True)
        assert chk is not None
        assert "password" not in chk.state_snapshot
        print(f"[PASSED] Stage: 6. Milestone Checkpoint Created - ID: {chk.checkpoint_id}")
        passed_stages += 1

        # STAGE 7: Intermediate Outcome Evaluation
        dummy_step = planned_task.steps[0]
        tool_res = ToolResult(
            request_id="test",
            tool_name=dummy_step.tool_name,
            success=True,
            verified=True,
            status=ToolExecutionStatus.SUCCEEDED,
            output={"status": "ok"},
        )
        eval_outcome = evaluator.evaluate_step_result(dummy_step, tool_res)
        assert eval_outcome.category == StepEvaluationCategory.SUCCESS
        assert eval_outcome.is_verified is True
        print(f"[PASSED] Stage: 7. Step Result Evaluation - Verified: {eval_outcome.is_verified}")
        passed_stages += 1

        # STAGE 8: Failure Diagnosis & Classification
        diagnostician = FailureDiagnostician()
        diag = diagnostician.diagnose_failure(
            error_message="File 'missing_data.txt' does not exist",
            tool_name="file.read",
        )
        assert diag.category == ReasoningFailureCategory.TARGET_NOT_FOUND
        assert diag.retryable is True
        assert diag.replannable is True
        print(f"[PASSED] Stage: 8. Failure Diagnosis - Category: {diag.category.value}, Retryable: {diag.retryable}")
        passed_stages += 1

        # STAGE 9: Bounded Safe Replanning
        replanner = SafeReplanner(registry, evaluator, diagnostician)
        fail_step = TaskStep(
            sequence=1,
            description="Read data file",
            tool_name="file.read",
            arguments={"path": str(workspace_dir / "nonexistent.txt")},
        )
        test_task = Task(user_goal="Read data", steps=[fail_step])
        replan_ok = replanner.replan_failed_step(test_task, fail_step, diag)
        assert replan_ok is True
        assert test_task.replan_count == 1
        print(f"[PASSED] Stage: 9. Bounded Safe Replanning - Replan count: {test_task.replan_count}")
        passed_stages += 1

        # STAGE 10: Task Budget Bounds & Exhaustion
        budget = TaskBudget(max_total_steps=2, max_replans=1)
        budget.start()
        budget.record_step()
        budget.record_step()
        exhausted, reason = budget.is_exhausted()
        assert exhausted is True
        print(f"[PASSED] Stage: 10. Task Budget Bounds - Reason: {reason}")
        passed_stages += 1

        # STAGE 11: Specialist Roles Capability Boundaries
        researcher = ResearcherRole()
        coder = CoderRole()
        verifier = VerifierRole()
        assert researcher.is_tool_allowed("file.read") is True
        assert researcher.is_tool_allowed("file.create") is False
        assert coder.is_tool_allowed("file.create") is True
        assert verifier.is_tool_allowed("file.read") is True
        print("[PASSED] Stage: 11. Specialist Roles Boundaries Enforced")
        passed_stages += 1

        # STAGE 12: Safe Parallel Execution Coordinator
        parallel_coord = SafeParallelCoordinator(tool_executor)
        read_step1 = TaskStep(description="Info 1", tool_name="system.info", arguments={})
        read_step2 = TaskStep(description="Info 2", tool_name="system.info", arguments={})
        assert parallel_coord.can_parallelize_steps([read_step1, read_step2]) is True
        # Prohibited parallel tool (file creation)
        write_step = TaskStep(description="Write", tool_name="file.create", arguments={"path": "a.txt"})
        assert parallel_coord.can_parallelize_steps([read_step1, write_step]) is False
        print("[PASSED] Stage: 12. Safe Parallel Execution Gating")
        passed_stages += 1

    print("======================================================================")
    print(f"SMOKE TEST SUMMARY: {passed_stages}/{total_stages} PASSED")
    print("======================================================================")
    return 0 if passed_stages == total_stages else 1


def main() -> int:
    return asyncio.run(run_smoke_test())


if __name__ == "__main__":
    sys.exit(main())
