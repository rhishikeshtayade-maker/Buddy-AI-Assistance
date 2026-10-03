"""BUDDY CLI Chat Mode (Development Harness).

Run directly via:
    python -m app.ai.chat

Provides an interactive command-line interface for conversing with BUDDY
without requiring microphone hardware.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Optional

from app import __product__, __version__
from app.ai.conversation import ConversationManager
from app.ai.router import AIRouter
from app.core import BuddyConfig, BuddyState, EventBus, StateMachine


async def run_cli_chat() -> int:
    config = BuddyConfig.load_from_env()
    event_bus = EventBus()
    state_machine = StateMachine(BuddyState.IDLE)
    router = AIRouter(config)

    conversation_mgr = ConversationManager(
        config=config,
        event_bus=event_bus,
        state_machine=state_machine,
        router=router,
    )

    active_provider = router.get_provider()
    pending_confirmation: list[Any] = []

    async def _on_confirm_needed(event: Any) -> None:
        pending_confirmation.append(event)

    event_bus.subscribe(
        __import__("app.tools").tools.ToolConfirmationRequiredEvent,
        _on_confirm_needed,
    )

    print("========================================================================")
    print(f"                   {__product__} v{__version__} — AI CHAT MODE")
    print(f"       Provider: {active_provider.provider_name} | Model: {config.ai_model}")
    print("                    Type 'exit' or 'quit' to end.")
    print("========================================================================\n")

    confirmation_token: Optional[str] = None

    while True:
        try:
            # Read input synchronously in executor to allow clean cancellation
            loop = asyncio.get_running_loop()

            if pending_confirmation:
                conf_event = pending_confirmation.pop(0)
                prompt_str = f"[CONFIRM] Allow '{conf_event.tool_name}' ({conf_event.arguments})? [y/N]: "
                user_input = await loop.run_in_executor(None, input, prompt_str)
                if user_input.strip().lower() in ("y", "yes"):
                    confirmation_token = conf_event.token
                    user_text = f"Confirmed tool execution with token {conf_event.token}"
                else:
                    confirmation_token = None
                    user_text = "Action cancelled by user"
            else:
                user_input = await loop.run_in_executor(None, input, "You: ")
                user_text = user_input.strip()

            if not user_text:
                continue

            if user_text.lower() in ("exit", "quit", "q"):
                print("\nBUDDY: Goodbye! Have a great day.")
                break

            response = await conversation_mgr.process_user_turn(
                user_text,
                voice_response=False,
                confirmation_token=confirmation_token,
            )
            confirmation_token = None
            print(f"BUDDY: {response.content}\n")

        except (KeyboardInterrupt, EOFError):
            print("\n\nBUDDY: Session terminated. Goodbye!")
            break
        except Exception as err:
            print(f"\n[ERROR] BUDDY encountered an issue: {err}\n")

    await event_bus.shutdown()
    return 0


def main() -> int:
    return asyncio.run(run_cli_chat())


if __name__ == "__main__":
    sys.exit(main())
