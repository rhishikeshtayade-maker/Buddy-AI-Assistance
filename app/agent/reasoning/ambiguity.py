"""BUDDY Ambiguity Detection & Clarification Subsystem (Loop 12).

Detects unresolvable, ambiguous, or multi-candidate intents in user goals and targets.
Ensures BUDDY never guesses on high-risk, destructive, or underspecified operations.
"""

from __future__ import annotations

import re
from typing import List, Optional

from app.agent.reasoning.models import ClarificationRequest


class AmbiguityDetector:
    """Analyzes user goal strings, paths, and target descriptions for hazardous ambiguity."""

    _DESTRUCTIVE_WORDS = {
        "delete", "remove", "erase", "format", "wipe", "drop", "purge", "kill", "terminate"
    }

    _GENERIC_TARGETS = {
        "the file", "the document", "the folder", "the window", "it", "them", "that", "the app", "the tab"
    }

    def detect_goal_ambiguity(
        self,
        objective: str,
        detected_candidates: Optional[List[str]] = None,
    ) -> Optional[ClarificationRequest]:
        """Examine objective text and candidate counts to determine if clarification is required.

        Returns:
            ClarificationRequest if ambiguity is detected, otherwise None.
        """
        lower_obj = objective.strip().lower()

        # 1. Multiple candidates detected for an operation
        if detected_candidates and len(detected_candidates) > 1:
            return ClarificationRequest(
                question=f"Multiple matching targets found: {', '.join(detected_candidates[:5])}. Which one did you mean?",
                affected_requirement="target_resolution",
                possible_interpretations=detected_candidates[:5],
                risk_level="HIGH" if any(w in lower_obj for w in self._DESTRUCTIVE_WORDS) else "MEDIUM",
                is_blocking=True,
            )

        # 2. Destructive action with underspecified target
        has_destructive = any(re.search(rf"\b{w}\b", lower_obj) for w in self._DESTRUCTIVE_WORDS)
        if has_destructive:
            if any(generic in lower_obj for generic in self._GENERIC_TARGETS) and not re.search(r"[\w\-\.]+\.\w{2,4}", lower_obj):
                return ClarificationRequest(
                    question="Destructive operation requested on an unspecified target. Which specific file or item should be affected?",
                    affected_requirement="target_identity",
                    possible_interpretations=["Specific filename required", "Cancel operation"],
                    risk_level="HIGH",
                    is_blocking=True,
                )

        # 3. Destination missing in file movement / copy
        if any(verb in lower_obj for verb in ["move", "copy", "transfer"]) and "to " not in lower_obj and "into " not in lower_obj:
            return ClarificationRequest(
                question="A file operation was requested, but no destination was specified. Where should it be copied or moved?",
                affected_requirement="destination_path",
                possible_interpretations=["Specify destination directory", "Cancel operation"],
                risk_level="MEDIUM",
                is_blocking=True,
            )

        # 4. Conflicting constraints (e.g., delete and keep)
        if "delete" in lower_obj and "keep" in lower_obj:
            return ClarificationRequest(
                question="Conflicting instructions detected (both 'delete' and 'keep' mentioned). Please clarify the intended outcome.",
                affected_requirement="goal_consistency",
                possible_interpretations=["Keep existing files", "Delete existing files"],
                risk_level="HIGH",
                is_blocking=True,
            )

        return None
