"""BUDDY Builtin Tool Registration.

Registers all standard, verified safe computer control tools into a ToolRegistry instance.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from app.tools.applications import AppCloseTool, AppListTool, AppOpenTool
from app.tools.filesystem import (
    FileCopyTool,
    FileCreateTool,
    FileMoveTool,
    FileReadTool,
    FileRenameTool,
    FileSearchTool,
)
from app.tools.keyboard import KeyPressTool, TypeTextTool
from app.tools.mouse import (
    MouseClickTool,
    MouseDoubleClickTool,
    MouseScrollTool,
)
from app.tools.registry import ToolRegistry
from app.tools.system import (
    SystemBatteryTool,
    SystemGetVolumeTool,
    SystemInfoTool,
    SystemSetVolumeTool,
)

if TYPE_CHECKING:
    from app.browser.service import BrowserService
    from app.security.interaction_policy import InteractionPolicy
    from app.security.path_policy import PathPolicy

logger = logging.getLogger("buddy.tools.builtin")


def register_builtin_tools(
    registry: ToolRegistry,
    path_policy: Optional[PathPolicy] = None,
    interaction_policy: Optional[InteractionPolicy] = None,
    browser_service: Optional[BrowserService] = None,
    include_browser: bool = False,
) -> None:
    """Register all standard built-in tools with the registry."""
    from app.security.interaction_policy import InteractionPolicy
    from app.security.path_policy import PathPolicy

    policy = path_policy or PathPolicy()
    ipolicy = interaction_policy or InteractionPolicy()

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

    # Controlled Mouse & Keyboard Interaction Controls (Loop 6)
    registry.register_tool(MouseClickTool(ipolicy))
    registry.register_tool(MouseDoubleClickTool(ipolicy))
    registry.register_tool(MouseScrollTool(ipolicy))
    registry.register_tool(KeyPressTool(ipolicy))
    registry.register_tool(TypeTextTool(ipolicy))

    # Browser Automation Controls (Loop 9)
    if browser_service or include_browser:
        from app.browser.registry import register_browser_tools
        from app.browser.service import BrowserService
        bs = browser_service or BrowserService(path_policy=policy)
        register_browser_tools(registry, bs)

    logger.info("Registered all builtin tools (%d total)", len(registry.list_tools()))
