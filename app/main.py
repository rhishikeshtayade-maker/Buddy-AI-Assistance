"""BUDDY — Main Entry Point.

BUDDY: Your Voice. Your Laptop. Your Control.
Loop 1 Core Runtime initialization and orchestrator.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Ensure project root is in sys.path when executed directly as a script
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app import __product__, __tagline__, __version__
from app.core import BuddyConfig, HealthStatus, LifecycleManager


def print_banner() -> None:
    """Display product banner and brand identity."""
    banner = f"""========================================================================
   ____  _   _ ____  ______   __
  | __ )| | | |  _ \\|  _ \\ \\ / /
  |  _ \\| | | | | | | | | \\ V / 
  | |_) | |_| | |_| | |_| || |  
  |____/ \\___/|____/|____/ |_|  
  
  {__product__} v{__version__}
  "{__tagline__}"
========================================================================"""
    print(banner)


async def run_buddy(keep_alive: bool = False) -> int:
    """Initialize core runtime, verify health, and optionally enter execution loop."""
    print_banner()
    print("\nInitializing...")

    lifecycle = LifecycleManager(BuddyConfig.load_from_env())

    try:
        # 1. Initialize services
        await lifecycle.initialize()
        print("Configuration: OK")
        print("Core services: OK")

        # 2. Run initial health checks and start
        health_report = await lifecycle.start()
        health_str = health_report.status.value
        print(f"Health: {health_str}")

        print("\nBUDDY is ready.")
        print(f"State: {lifecycle.state_machine.current_state.value}")

        if health_report.status == HealthStatus.UNHEALTHY:
            await lifecycle.shutdown(reason="Unhealthy startup state")
            return 1

        if keep_alive:
            print("\nEntering event loop. Press Ctrl+C to terminate.")
            await lifecycle.run()
        else:
            await lifecycle.shutdown(reason="CLI foundation check complete")

        return 0

    except Exception as err:
        print(f"\n[FATAL] BUDDY failed to start: {err}", file=sys.stderr)
        try:
            await lifecycle.shutdown(reason=f"Startup failure: {err}")
        except Exception:
            pass
        return 1


def main(args: list[str] | None = None) -> int:
    """Synchronous entry point compatible with console scripts and testing harnesses."""
    parser = argparse.ArgumentParser(description="BUDDY — Secure AI Desktop Assistant")
    parser.add_argument(
        "--run",
        action="store_true",
        help="Keep BUDDY running in daemon/interactive mode until terminated",
    )
    # If args is None, treat as empty list to prevent argparse inspecting sys.argv during unit tests
    parsed = parser.parse_args([] if args is None else args)

    return asyncio.run(run_buddy(keep_alive=parsed.run))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
