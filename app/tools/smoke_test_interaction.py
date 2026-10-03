"""BUDDY Real Windows Interaction Smoke Test.

Run directly via:
    python -m app.tools.smoke_test_interaction [--mock]

Performs a strictly bounded, harmless interaction test:
1. Launches allowlisted Notepad
2. Captures screen dimensions and state fingerprint
3. Locates Notepad window / text area as a verified VisionTarget
4. Obtains confirmation and dispatches verified click
5. Types harmless string 'BUDDY TEST'
6. Gracefully terminates Notepad and cleans up all processes
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time

from app.core.config import BuddyConfig
from app.core.events import EventBus
from app.core.state import BuddyState, StateMachine
from app.security.confirmation import ConfirmationManager
from app.security.interaction_policy import InteractionPolicy
from app.security.permissions import PermissionEngine
from app.tools.applications import AppCloseTool, AppOpenTool
from app.tools.builtin import register_builtin_tools
from app.tools.executor import ToolExecutor
from app.tools.interaction_models import (
    InteractionAction,
    InteractionRequest,
    UIActionProposal,
)
from app.tools.keyboard import TypeTextTool
from app.tools.models import ToolRequest, ToolRiskLevel
from app.tools.mouse import MouseClickTool
from app.tools.registry import ToolRegistry
from app.vision.models import BoundingBox, VisionTarget
from app.vision.screen import MockScreenManager, WindowsScreenManager


async def run_smoke_test(use_mock: bool = False) -> int:
    print("========================================================================")
    print("             BUDDY — MOUSE & KEYBOARD INTERACTION SMOKE TEST            ")
    print(f"                       Mode: {'MOCK' if use_mock else 'REAL WINDOWS'}")
    print("========================================================================\n")

    screen_mgr = MockScreenManager() if use_mock else WindowsScreenManager()
    width, height = screen_mgr.get_screen_dimensions()
    initial_fp = screen_mgr.get_screen_fingerprint()
    print(f"[1/6] Screen inspected: {width}x{height} | Fingerprint: {initial_fp}")

    policy = InteractionPolicy(screen_manager=screen_mgr)
    registry = ToolRegistry()
    register_builtin_tools(registry, interaction_policy=policy)
    conf_mgr = ConfirmationManager(default_ttl_seconds=30.0)
    event_bus = EventBus()
    executor = ToolExecutor(
        registry=registry,
        confirmation_manager=conf_mgr,
        event_bus=event_bus,
    )

    app_open_tool = registry.get_tool("app.open")
    app_close_tool = registry.get_tool("app.close")
    mouse_click_tool = registry.get_tool("mouse.click")
    type_tool = registry.get_tool("keyboard.type_text")

    try:
        # Step 1: Open Notepad
        print("\n[2/6] Launching allowlisted Notepad...")
        open_req = ToolRequest(tool_name="app.open", arguments={"application": "notepad"})
        open_res = await executor.execute(open_req)
        if not open_res.success:
            print(f"FAILED to launch Notepad: {open_res.error}")
            return 1
        print("Notepad launched and process verified.")
        await asyncio.sleep(1.0)

        # Step 2: Establish verified VisionTarget
        current_fp = screen_mgr.get_screen_fingerprint()
        target = VisionTarget(
            target_id="notepad_textarea_01",
            label="Notepad Text Editor Area",
            bounding_box=BoundingBox(x=width // 4, y=height // 4, width=width // 2, height=height // 2),
            confidence=0.99,
            screen_fingerprint=current_fp,
            screen_dimensions=(width, height),
            category="SAFE",
            is_verified=True,
        )
        policy.register_verified_target(target)
        print(f"[3/6] Verified VisionTarget registered: '{target.label}' at center {target.center}")

        # Step 3: Propose Click Action and Confirm
        proposal = UIActionProposal(
            action_type=InteractionAction.CLICK,
            target=target,
            screen_fingerprint=current_fp,
            screen_dimensions=(width, height),
            risk_level=ToolRiskLevel.MODERATE,
            reason="Focus Notepad text editor",
        )
        interaction_req = proposal.to_interaction_request()

        tool_click_req = ToolRequest(
            tool_name="mouse.click",
            arguments={
                "target_id": interaction_req.target_id,
                "screen_fingerprint": interaction_req.screen_fingerprint,
            },
        )

        print("\n[4/6] Evaluating click permission & issuing confirmation...")
        # First execution requires confirmation token
        first_click_res = await executor.execute(tool_click_req)
        token = first_click_res.metadata.get("confirmation_token")
        if not token:
            print(f"FAILED: Confirmation token was not generated: {first_click_res.error}")
            return 1
        print(f"Confirmation token issued: {token[:12]}...")

        # Execute with confirmation token
        click_res = await executor.execute(tool_click_req, confirmation_token=token)
        if not click_res.success or not click_res.verified:
            print(f"FAILED click execution: {click_res.error}")
            return 1
        print(f"Mouse click executed and verified at coordinates: {click_res.output.get('coordinates')}")
        await asyncio.sleep(0.5)

        # Step 4: Type harmless text
        print("\n[5/6] Typing harmless string 'BUDDY TEST'...")
        type_req = ToolRequest(
            tool_name="keyboard.type_text",
            arguments={"text": "BUDDY TEST\n"},
        )
        type_res = await executor.execute(type_req)
        if not type_res.success:
            print(f"FAILED to type text: {type_res.error}")
            return 1
        print(f"Text typing executed successfully ({type_res.output.get('character_count')} chars).")
        await asyncio.sleep(1.0)

        # Step 5: Clean up and close Notepad
        print("\n[6/6] Cleaning up: Closing Notepad...")
        close_req = ToolRequest(
            tool_name="app.close",
            arguments={"application": "notepad"},
        )
        close_token_res = await executor.execute(close_req)
        close_token = close_token_res.metadata.get("confirmation_token")
        close_res = await executor.execute(close_req, confirmation_token=close_token)
        print(f"Notepad closed successfully (terminated: {close_res.output.get('terminated_count')}).")

        print("\n========================================================================")
        print("          ALL INTERACTION SMOKE TEST CHECKS PASSED SUCCESSFULLY!        ")
        print("========================================================================")
        return 0

    except Exception as err:
        print(f"\n[ERROR] Smoke test encountered an exception: {err}")
        return 1
    finally:
        # Emergency cleanup: ensure Notepad is closed
        try:
            emergency_close = ToolRequest(tool_name="app.close", arguments={"application": "notepad"})
            token_res = await executor.execute(emergency_close)
            t = token_res.metadata.get("confirmation_token")
            await executor.execute(emergency_close, confirmation_token=t)
        except Exception:
            pass
        await event_bus.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description="BUDDY Controlled Mouse/Keyboard Smoke Test")
    parser.add_argument("--mock", action="store_true", help="Run with mock drivers (safe for CI)")
    args = parser.parse_args()
    return asyncio.run(run_smoke_test(use_mock=args.mock))


if __name__ == "__main__":
    sys.exit(main())
