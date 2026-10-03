"""BUDDY Task Context & Bounded Working Memory.

Maintains scoped, task-relevant state during multi-step execution.
Excludes secrets, raw pixel buffers, and unrestricted system data.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from app.ai.prompts import wrap_untrusted_content
from app.core.logging import redact_sensitive_data
from app.tools.models import ToolResult
from app.vision.models import VisionTarget

logger = logging.getLogger("buddy.agent.context")


class TaskContext(BaseModel):
    """Scoped, ephemeral working state for an active agent task."""

    task_id: str
    user_goal: str
    conversation_id: Optional[str] = None
    screen_fingerprint: Optional[str] = None
    screen_dimensions: Optional[Tuple[int, int]] = None
    active_applications: Set[str] = Field(default_factory=set)
    discovered_targets: Dict[str, VisionTarget] = Field(default_factory=dict)
    completed_steps_summary: List[Dict[str, Any]] = Field(default_factory=list)
    step_results: Dict[str, Any] = Field(default_factory=dict)
    untrusted_artifacts: List[str] = Field(default_factory=list)
    max_history_entries: int = 20

    model_config = {"arbitrary_types_allowed": True}

    def record_step_result(self, step_id: str, tool_name: str, result: ToolResult) -> None:
        """Record a verified step outcome in bounded task memory."""
        # Sanitize output before storing
        clean_output = redact_sensitive_data(result.output) if result.output else None

        self.step_results[step_id] = {
            "tool_name": tool_name,
            "success": result.success,
            "verified": result.verified,
            "output": clean_output,
            "latency": result.execution_latency,
        }

        summary_entry = {
            "step_id": step_id,
            "tool": tool_name,
            "status": "SUCCEEDED" if result.success and result.verified else "FAILED",
        }
        self.completed_steps_summary.append(summary_entry)

        # Enforce bounded history
        if len(self.completed_steps_summary) > self.max_history_entries:
            self.completed_steps_summary = self.completed_steps_summary[-self.max_history_entries:]

        # If output came from external source (like file read), record wrapped untrusted artifact
        if clean_output and isinstance(clean_output, str) and len(clean_output) > 0:
            wrapped = wrap_untrusted_content(clean_output[:500], source=f"tool:{tool_name}")
            self.untrusted_artifacts.append(wrapped)
            if len(self.untrusted_artifacts) > 10:
                self.untrusted_artifacts = self.untrusted_artifacts[-10:]

    def register_target(self, target: VisionTarget) -> None:
        """Cache a discovered VisionTarget within the current task context."""
        self.discovered_targets[target.target_id] = target
        logger.debug("TaskContext %s registered target %s", self.task_id, target.target_id)

    def get_target(self, target_id: str) -> Optional[VisionTarget]:
        return self.discovered_targets.get(target_id)

    def update_screen_state(self, fingerprint: str, dimensions: Tuple[int, int]) -> None:
        self.screen_fingerprint = fingerprint
        self.screen_dimensions = dimensions

    def to_safe_prompt_context(self) -> str:
        """Render a concise, secret-free summary of current context for planning or re-planning."""
        apps = ", ".join(sorted(self.active_applications)) or "None tracked"
        steps_done = len(self.completed_steps_summary)
        targets = [f"{t.target_id} ('{t.label}')" for t in self.discovered_targets.values()]
        targets_str = ", ".join(targets) or "None"

        return (
            f"Goal: {self.user_goal}\n"
            f"Active Apps: {apps}\n"
            f"Screen Fingerprint: {self.screen_fingerprint or 'Unknown'}\n"
            f"Discovered Targets: {targets_str}\n"
            f"Steps Completed: {steps_done}\n"
        )
