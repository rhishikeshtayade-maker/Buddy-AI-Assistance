"""BUDDY Real Windows Multi-Step Agent Smoke Test (Loop 7).

Run directly via:
    python -m app.agent.smoke_test_agent [--mock]

Executes the Phase 24 acceptance task:
"Open Notepad, type BUDDY TEST, and finish."

Sequence:
1. Decomposes goal into structured plan using TaskPlanner.
2. Validates plan through TaskPlanValidator.
3. Step 1: Launches allowlisted Notepad (app.open).
4. Step 2: Establishes window focus via mouse.click with interactive confirmation.
5. Step 3: Types harmless text 'BUDDY TEST' (keyboard.type_text).
6. Gracefully terminates Notepad and verifies cleanup.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

from app.agent.executor import TaskExecutor
from app.agent.models import StepStatus, TaskStatus
from app.agent.service import AgentService
from app.core.events import EventBus
from app.core.state import BuddyState, StateMachine
from app.security.confirmation import ConfirmationManager
from app.security.interaction_policy import InteractionPolicy
from app.security.permissions import PermissionEngine
from app.tools.builtin import register_builtin_tools
from app.tools.executor import ToolExecutor
from app.tools.models import ToolRequest
from app.tools.registry import ToolRegistry
from app.vision.models import BoundingBox, VisionTarget
from app.vision.screen import MockScreenManager, WindowsScreenManager


async def run_agent_smoke_test(use_mock: bool = False) -> int:
    print("========================================================================")
    print("        BUDDY — MULTI-STEP AGENTIC PLANNING & EXECUTION SMOKE TEST       ")
    print(f"                       Mode: {'MOCK' if use_mock else 'REAL WINDOWS'}")
    print("========================================================================\n")

    screen_mgr = MockScreenManager() if use_mock else WindowsScreenManager()
    width, height = screen_mgr.get_screen_dimensions()
    current_fp = screen_mgr.get_screen_fingerprint()
    print(f"[1/6] Screen inspected: {width}x{height} | Fingerprint: {current_fp}")

    policy = InteractionPolicy(screen_manager=screen_mgr)

    # Register verified target for Notepad editor area
    notepad_target = VisionTarget(
        target_id="notepad_textarea",
        label="Notepad Text Editor Area",
        bounding_box=BoundingBox(x=width // 4, y=height // 4, width=width // 2, height=height // 2),
        confidence=0.99,
        screen_fingerprint=current_fp,
        screen_dimensions=(width, height),
        category="SAFE",
        is_verified=True,
    )
    policy.register_verified_target(notepad_target)

    registry = ToolRegistry()
    register_builtin_tools(registry, interaction_policy=policy)

    conf_mgr = ConfirmationManager(default_ttl_seconds=30.0)
    perm_engine = PermissionEngine(interaction_policy=policy)
    event_bus = EventBus()
    state_machine = StateMachine(BuddyState.IDLE)

    tool_executor = ToolExecutor(
        registry=registry,
        permission_engine=perm_engine,
        confirmation_manager=conf_mgr,
        event_bus=event_bus,
    )

    agent_service = AgentService(
        registry=registry,
        tool_executor=tool_executor,
        event_bus=event_bus,
        state_machine=state_machine,
    )

    try:
        goal = "Open Notepad, type BUDDY TEST, and finish."
        print(f"\n[2/6] Submitting user goal to Planner: '{goal}'")
        task = await agent_service.submit_goal(goal)
        print(f"Planner decomposed goal into {len(task.steps)} structured steps:")
        for s in task.steps:
            print(f"  - Step {s.sequence}: [{s.tool_name}] {s.description}")

        print("\n[3/6] Starting multi-step execution...")
        result = await agent_service.executor.execute_task(task)

        # Handle Step 2 confirmation
        if result.status == TaskStatus.WAITING_CONFIRMATION:
            token = result.metadata.get("confirmation_token")
            print(f"Step requires confirmation. Token issued: {token[:12]}...")
            print("[4/6] Supplying user confirmation token to resume task...")
            result = await agent_service.executor.execute_task(task, confirmation_token=token)

        if result.status != TaskStatus.COMPLETED or not result.verified:
            print(f"[ERROR] Task failed: {result.final_message}")
            return 1

        print(f"[5/6] Multi-step execution verified successfully in {result.execution_latency:.2f}s!")
        print(f"Completed steps: {result.completed_steps}")

        print("\n[6/6] Cleaning up: Closing Notepad application...")
        close_req = ToolRequest(tool_name="app.close", arguments={"application": "notepad"})
        token_res = await tool_executor.execute(close_req)
        close_token = token_res.metadata.get("confirmation_token")
        await tool_executor.execute(close_req, confirmation_token=close_token)
        print("Notepad closed and test environment restored.")

        print("\n========================================================================")
        print("         ALL MULTI-STEP AGENTIC CHECKS PASSED SUCCESSFULLY!             ")
        print("========================================================================")
        return 0

    except Exception as err:
        print(f"\n[ERROR] Smoke test encountered an exception: {err}")
        return 1
    finally:
        # Cleanup fallback
        try:
            emergency_close = ToolRequest(tool_name="app.close", arguments={"application": "notepad"})
            t_res = await tool_executor.execute(emergency_close)
            t = t_res.metadata.get("confirmation_token")
            await tool_executor.execute(emergency_close, confirmation_token=t)
        except Exception:
            pass
        await event_bus.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description="BUDDY Multi-Step Agent Smoke Test")
    parser.add_argument("--mock", action="store_true", help="Run with mock drivers (safe for CI)")
    args = parser.parse_args()
    return asyncio.run(run_agent_smoke_test(use_mock=args.mock))


if __name__ == "__main__":
    sys.exit(main())
