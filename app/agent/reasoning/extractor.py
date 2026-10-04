"""BUDDY Structured Goal and Requirement Extractor (Loop 12).

Parses natural-language user objectives into strongly typed Goal representations
containing requirements, constraints, assumptions, success criteria, and ambiguities.
"""

from __future__ import annotations

import re
from typing import Any, List, Optional

from app.agent.reasoning.ambiguity import AmbiguityDetector
from app.agent.reasoning.models import (
    ConfidenceAssessment,
    Goal,
    GoalAssumption,
    GoalConstraint,
    GoalPriority,
    GoalRequirement,
    GoalStatus,
)


class GoalRequirementExtractor:
    """Extracts structured requirements and constraints from natural language objectives."""

    def __init__(self, ambiguity_detector: Optional[AmbiguityDetector] = None) -> None:
        self._ambiguity = ambiguity_detector or AmbiguityDetector()

    def extract_goal(
        self,
        objective: str,
        conversation_id: Optional[str] = None,
        memory_preferences: Optional[List[str]] = None,
        detected_candidates: Optional[List[str]] = None,
    ) -> Goal:
        """Parse user prompt into a structured Goal model."""
        clean_obj = objective.strip()
        lower_obj = clean_obj.lower()

        requirements: List[GoalRequirement] = []
        constraints: List[GoalConstraint] = []
        assumptions: List[GoalAssumption] = []
        prohibited: List[str] = [
            "arbitrary_code_execution",
            "security_policy_modification",
            "direct_credential_access",
        ]

        # 1. Detect location constraints (e.g. Desktop, Downloads, Documents)
        target_path: Optional[str] = None
        for loc in ["desktop", "downloads", "documents", "temp", "workspace"]:
            if loc in lower_obj:
                constraints.append(
                    GoalConstraint(
                        constraint_type="output_directory",
                        description=f"Target output directory must be within {loc.capitalize()}",
                        strict=True,
                    )
                )
                target_path = loc

        # 2. Identify target files / names
        file_match = re.search(r"[\w\-\.]+\.(?:txt|md|json|csv|py|html|pdf)", clean_obj, re.IGNORECASE)
        target_filename = file_match.group(0) if file_match else None

        # 3. Detect action capabilities needed
        if any(w in lower_obj for w in ["browse", "web", "site", "url", "http", "search online"]):
            requirements.append(
                GoalRequirement(
                    description="Gather data or perform actions via web browser",
                    required_capability="browser",
                    verification_criteria="Browser navigation and content extraction succeed",
                )
            )

        if any(w in lower_obj for w in ["file", "create", "write", "rename", "delete", "copy", "report"]):
            desc = "Perform local filesystem operations"
            if target_filename:
                desc += f" targeting '{target_filename}'"
            requirements.append(
                GoalRequirement(
                    description=desc,
                    required_capability="filesystem",
                    verification_criteria=f"File '{target_filename or 'target'}' exists with expected content",
                )
            )

        if any(w in lower_obj for w in ["app", "launch", "open application", "window"]):
            requirements.append(
                GoalRequirement(
                    description="Launch or interact with local desktop application",
                    required_capability="desktop_app",
                    verification_criteria="Target application process appears in system process list",
                )
            )

        if any(w in lower_obj for w in ["verify", "check", "ensure", "confirm"]):
            constraints.append(
                GoalConstraint(
                    constraint_type="empirical_verification",
                    description="Final file, window, or state existence must be explicitly verified",
                    strict=True,
                )
            )

        # 4. Integrate memory preferences as soft constraints
        if memory_preferences:
            for pref in memory_preferences:
                constraints.append(
                    GoalConstraint(
                        constraint_type="user_preference",
                        description=f"User preference: {pref}",
                        strict=False,
                    )
                )

        # 5. Default assumptions
        if target_path:
            assumptions.append(
                GoalAssumption(
                    description=f"User has write permissions to standard {target_path.capitalize()} folder",
                    validated=True,
                )
            )

        # 6. Ambiguity detection
        clarification = self._ambiguity.detect_goal_ambiguity(clean_obj, detected_candidates)
        initial_status = GoalStatus.WAITING_CLARIFICATION if (clarification and clarification.is_blocking) else GoalStatus.PENDING

        priority = GoalPriority.HIGH if any(p in lower_obj for p in ["urgent", "immediately", "critical", "now"]) else GoalPriority.MEDIUM

        goal = Goal(
            conversation_id=conversation_id,
            objective=clean_obj,
            status=initial_status,
            priority=priority,
            requirements=requirements,
            constraints=constraints,
            assumptions=assumptions,
            prohibited_actions=prohibited,
            pending_clarification=clarification,
            confidence=ConfidenceAssessment.from_score(
                0.3 if clarification and clarification.is_blocking else 0.85,
                ["ambiguous_target"] if clarification else ["clear_requirements"],
            ),
        )

        return goal
