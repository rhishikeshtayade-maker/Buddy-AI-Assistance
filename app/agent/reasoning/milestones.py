"""BUDDY Milestone and Checkpoint Management Subsystem (Loop 12).

Tracks high-level milestone progress and safe recovery checkpoints.
Guarantees zero persistence of raw sensitive credentials or heavy payloads.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.agent.reasoning.models import (
    Checkpoint,
    Goal,
    GoalStatus,
    Milestone,
)


class MilestoneManager:
    """Manages milestone lifecycle, progress tracking, and checkpoint generation."""

    def initialize_milestones_from_goal(self, goal: Goal) -> List[Milestone]:
        """Derive standard milestones if none explicitly defined."""
        if goal.milestones:
            return goal.milestones

        milestones = [
            Milestone(
                title="Preparation & Discovery",
                success_criteria=["Inputs validated", "Prerequisite resources located"],
                status=GoalStatus.PENDING,
            ),
            Milestone(
                title="Action & Transformation",
                success_criteria=["Main operational steps executed"],
                status=GoalStatus.PENDING,
            ),
            Milestone(
                title="Empirical Verification",
                success_criteria=["Observable side effects confirmed on host"],
                status=GoalStatus.PENDING,
            ),
        ]
        goal.milestones = milestones
        return milestones

    def update_milestone_progress(
        self,
        goal: Goal,
        completed_step_id: str,
        step_verified: bool,
    ) -> Optional[Checkpoint]:
        """Update active milestone status and optionally record a recovery checkpoint."""
        for ms in goal.milestones:
            if ms.status in (GoalStatus.PENDING, GoalStatus.EXECUTING):
                ms.status = GoalStatus.EXECUTING
                if completed_step_id not in ms.required_steps:
                    ms.required_steps.append(completed_step_id)

                # Check if milestone can be marked complete
                if step_verified and len(ms.required_steps) >= 1:
                    ms.status = GoalStatus.COMPLETED
                    ms.verification_result = True
                    ms.completed_at = time.time()

                    # Create a safe checkpoint
                    checkpoint = Checkpoint(
                        milestone_id=ms.milestone_id,
                        completed_step_ids=list(ms.required_steps),
                        state_snapshot={
                            "milestone_title": ms.title,
                            "completed_at": ms.completed_at,
                            "verified": True,
                        },
                    )
                    goal.checkpoints.append(checkpoint)
                    return checkpoint
        return None
