"""BUDDY Agent Task Planner.

Converts natural-language goals into structured, validated Task plans.
Operates within a strictly sandboxed prompt context and NEVER executes actions directly.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from app.agent.context import TaskContext
from app.agent.events import (
    TaskCreatedEvent,
    TaskPlanCreatedEvent,
    TaskPlanRejectedEvent,
    TaskPlanningStartedEvent,
)
from app.agent.models import RetryPolicy, StepStatus, Task, TaskStep
from app.agent.validator import PlanValidationError, TaskPlanValidator
from app.ai.models import ChatMessage, MessageRole
from app.ai.provider import AIProvider
from app.core.events import EventBus
from app.tools.registry import ToolRegistry

logger = logging.getLogger("buddy.agent.planner")

PLANNER_SYSTEM_PROMPT = """You are the BUDDY Task Planner.
Your role is to decompose high-level user computer control goals into a sequence of structured steps.

AVAILABLE TOOLS:
{tool_specs}

CONSTRAINTS:
1. You may ONLY output a valid JSON object matching this schema:
{{
  "steps": [
    {{
      "description": "Short explanation of action",
      "tool_name": "exact.tool_name",
      "arguments": {{ ... }},
      "dependencies": []
    }}
  ]
}}
2. You must NEVER request shell commands, PowerShell, Python code, cmd.exe, or arbitrary code.
3. Every step must use an exact tool_name from the AVAILABLE TOOLS list.
4. Output raw JSON ONLY. No markdown fences, no explanatory chat.
"""


class TaskPlanner:
    """Decomposes natural language user goals into structured, dependency-ordered Task steps."""

    def __init__(
        self,
        registry: ToolRegistry,
        ai_provider: Optional[AIProvider] = None,
        validator: Optional[TaskPlanValidator] = None,
        event_bus: Optional[EventBus] = None,
        max_steps: int = 20,
    ) -> None:
        self._registry = registry
        self._ai_provider = ai_provider
        self._validator = validator or TaskPlanValidator(registry, max_steps=max_steps)
        self._event_bus = event_bus
        self._max_steps = max_steps

    def _format_tool_specs(self) -> str:
        """Format registered tools with input schemas and risk levels for the planner."""
        specs = []
        for defn in self._registry.list_tools():
            specs.append(
                f"- Tool: {defn.name} (Risk: {defn.risk_level.name})\n"
                f"  Description: {defn.description}\n"
                f"  Input Schema: {json.dumps(defn.input_schema)}"
            )
        return "\n".join(specs)

    async def plan(
        self,
        user_goal: str,
        context: Optional[TaskContext] = None,
        conversation_id: Optional[str] = None,
    ) -> Task:
        """Create and validate a Task plan for the given goal."""
        task_id = str(uuid.uuid4())

        if self._event_bus:
            await self._event_bus.publish(
                TaskCreatedEvent(task_id=task_id, user_goal=user_goal, conversation_id=conversation_id)
            )
            await self._event_bus.publish(
                TaskPlanningStartedEvent(task_id=task_id, user_goal=user_goal)
            )

        # 1. Deterministic Goal Parser Fallback (for testing / offline or direct decomposition)
        task = self._try_deterministic_plan(task_id, user_goal, conversation_id)

        # 2. If no deterministic match, call AIProvider
        if not task:
            if not self._ai_provider:
                raise PlanValidationError("No AIProvider configured and no deterministic plan matched goal.")
            task = await self._generate_ai_plan(task_id, user_goal, context, conversation_id)

        # 3. Validate the plan using TaskPlanValidator
        try:
            validated_task = self._validator.validate_plan(task)
        except Exception as e:
            if self._event_bus:
                await self._event_bus.publish(
                    TaskPlanRejectedEvent(task_id=task_id, reason=str(e))
                )
            raise

        if self._event_bus:
            tool_names = [s.tool_name for s in validated_task.steps]
            await self._event_bus.publish(
                TaskPlanCreatedEvent(
                    task_id=task_id,
                    step_count=len(validated_task.steps),
                    tools_planned=tool_names,
                )
            )

        return validated_task

    async def _generate_ai_plan(
        self,
        task_id: str,
        user_goal: str,
        context: Optional[TaskContext],
        conversation_id: Optional[str],
    ) -> Task:
        """Invoke AIProvider with restricted prompt to produce structured JSON plan."""
        tool_specs = self._format_tool_specs()
        system_prompt = PLANNER_SYSTEM_PROMPT.format(tool_specs=tool_specs)

        user_content = f"Goal: {user_goal}"
        if context:
            user_content += f"\nContext:\n{context.to_safe_prompt_context()}"

        messages = [ChatMessage(role=MessageRole.USER, content=user_content)]

        response = await self._ai_provider.generate(
            messages=messages,
            system_prompt=system_prompt,
            temperature=0.0,
            max_tokens=1000,
        )

        content = response.content.strip()
        # Strip potential markdown code fences ```json ... ```
        if content.startswith("```"):
            content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content).strip()

        try:
            data = json.loads(content)
        except Exception as json_err:
            raise PlanValidationError(f"Failed to parse planner output as JSON: {json_err} (raw: {content[:100]})")

        raw_steps = data.get("steps", [])
        if not isinstance(raw_steps, list):
            raise PlanValidationError("Planner output 'steps' must be a list.")

        steps: List[TaskStep] = []
        for idx, item in enumerate(raw_steps, start=1):
            if not isinstance(item, dict):
                raise PlanValidationError(f"Step {idx} must be a dictionary.")
            step = TaskStep(
                step_id=item.get("step_id") or f"step_{idx:02d}",
                sequence=idx,
                description=item.get("description", f"Step {idx}"),
                tool_name=item.get("tool_name", ""),
                arguments=item.get("arguments", {}),
                dependencies=item.get("dependencies", []),
                expected_result=item.get("expected_result"),
            )
            steps.append(step)

        return Task(
            task_id=task_id,
            conversation_id=conversation_id,
            user_goal=user_goal,
            steps=steps,
            max_steps=self._max_steps,
        )

    def _try_deterministic_plan(
        self,
        task_id: str,
        user_goal: str,
        conversation_id: Optional[str],
    ) -> Optional[Task]:
        """Produce deterministic plans for common multi-step patterns."""
        goal_lower = user_goal.lower()

        # Pattern: "Open Notepad, type <text>, and finish"
        if "open notepad" in goal_lower and "type" in goal_lower:
            text_match = re.search(r"type\s+([^,]+)", user_goal, re.IGNORECASE)
            text_to_type = text_match.group(1).strip() if text_match else "BUDDY TEST"
            # Remove any trailing "and finish"
            text_to_type = re.sub(r"(?i)\s+and\s+(finish|done|close).*", "", text_to_type).strip()

            step1 = TaskStep(
                step_id="step_open_notepad",
                sequence=1,
                description="Launch allowlisted Notepad application",
                tool_name="app.open",
                arguments={"application": "notepad"},
            )
            step2 = TaskStep(
                step_id="step_focus_editor",
                sequence=2,
                description="Click text editor area to establish window focus",
                tool_name="mouse.click",
                arguments={"target_id": "notepad_textarea"},
                dependencies=["step_open_notepad"],
            )
            step3 = TaskStep(
                step_id="step_type_content",
                sequence=3,
                description=f"Type harmless text string into editor",
                tool_name="keyboard.type_text",
                arguments={"text": text_to_type},
                dependencies=["step_focus_editor"],
            )
            return Task(
                task_id=task_id,
                conversation_id=conversation_id,
                user_goal=user_goal,
                steps=[step1, step2, step3],
                max_steps=self._max_steps,
            )

        # Pattern: "Open Calculator and get battery"
        if "open calculator" in goal_lower and "battery" in goal_lower:
            step1 = TaskStep(
                step_id="step_open_calc",
                sequence=1,
                description="Launch Calculator",
                tool_name="app.open",
                arguments={"application": "calc"},
            )
            step2 = TaskStep(
                step_id="step_get_battery",
                sequence=2,
                description="Query battery level",
                tool_name="system.get_battery",
                arguments={},
            )
            return Task(
                task_id=task_id,
                conversation_id=conversation_id,
                user_goal=user_goal,
                steps=[step1, step2],
                max_steps=self._max_steps,
            )

        return None
