"""BUDDY Builtin Tool Registration.

Registers all standard, verified safe computer control tools into a ToolRegistry instance.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.security.path_policy import PathPolicy
from app.tools.applications import AppCloseTool, AppListTool, AppOpenTool
from app.tools.filesystem import (
    FileCopyTool,
    FileCreateTool,
    FileMoveTool,
    FileReadTool,
    FileRenameTool,
    FileSearchTool,
)
from app.tools.registry import ToolRegistry
from app.tools.system import (
    SystemBatteryTool,
    SystemGetVolumeTool,
    SystemInfoTool,
    SystemSetVolumeTool,
)

logger = logging.getLogger("buddy.tools.builtin")


def register_builtin_tools(
    registry: ToolRegistry,
    path_policy: Optional[PathPolicy] = None,
) -> None:
    """Register all standard built-in tools with the registry."""
    policy = path_policy or PathPolicy()

    # System Diagnostics & Controls
    registry.register_tool(SystemInfoTool())
    registry.register_tool(SystemBatteryTool())
    registry.register_tool(SystemGetVolumeTool())
    registry.register_tool(SystemSetVolumeTool())

    # Application Controls
    registry.register_tool(AppListTool())
    registry.register_tool(AppOpenTool())
    registry.register_tool(AppCloseTool())

    # Sandboxed Filesystem Controls
    registry.register_tool(FileSearchTool(policy))
    registry.register_tool(FileReadTool(policy))
    registry.register_tool(FileCreateTool(policy))
    registry.register_tool(FileRenameTool(policy))
    registry.register_tool(FileCopyTool(policy))
    registry.register_tool(FileMoveTool(policy))

    logger.info("Registered all builtin tools (%d total)", len(registry.list_tools()))
