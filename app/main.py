"""BUDDY — Main Entry Point.

BUDDY: Your Voice. Your Laptop. Your Control.
"""

import sys
import logging
from pathlib import Path

# Ensure project root is in sys.path when executed directly as a script
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from app import __version__, __product__, __tagline__

# Configure basic logging for early bootstrap
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("buddy.main")


def print_banner() -> None:
    banner = f"""
========================================================================
   ____  _   _ ____  ______   __
  | __ )| | | |  _ \\|  _ \\ \\ / /
  |  _ \\| | | | | | | | | \\ V / 
  | |_) | |_| | |_| | |_| || |  
  |____/ \\___/|____/|____/ |_|  
  
  {__product__} v{__version__}
  "{__tagline__}"
========================================================================
    """
    print(banner)


def main() -> int:
    """Primary application entry point."""
    print_banner()
    logger.info("Starting BUDDY bootstrap sequence...")
    logger.info(f"Platform: {sys.platform} | Python: {sys.version.split()[0]}")
    logger.info("Loop 0 Foundation active. Ready for Loop 1 Core initialization.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
