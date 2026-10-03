"""BUDDY Tool Registry.

Provides thread-safe storage, discovery, and registration for authorized tools.
Untrusted agents or external models cannot register executable tools.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

from app.core.exceptions import RegistryError
from app.tools.base import Tool
from app.tools.models import ToolDefinition

logger = logging.getLogger("buddy.tools.registry")


class ToolRegistry:
    """Thread-safe registry for validated BUDDY tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}
        self._lock = threading.RLock()

    def register_tool(self, tool: Tool) -> None:
        """Register a tool instance.

        Raises:
            RegistryError: If tool is invalid, duplicate, or malformed.
        """
        if not isinstance(tool, Tool):
            raise RegistryError(f"Cannot register object of type '{type(tool).__name__}': must inherit from Tool.")

        definition = tool.definition
        if not isinstance(definition, ToolDefinition):
            raise RegistryError(f"Tool definition must be an instance of ToolDefinition, got {type(definition)}.")

        name = definition.name
        with self._lock:
            if name in self._tools:
                raise RegistryError(f"Tool '{name}' is already registered. Duplicate registration rejected.")

            self._tools[name] = tool
            logger.info("Registered tool: '%s' (risk=%s, perm=%s)", name, definition.risk_level.name, definition.permission_level.value)

    def unregister_tool(self, name: str) -> bool:
        """Remove a tool from the registry.

        Returns:
            True if tool was removed, False if tool was not found.
        """
        with self._lock:
            if name in self._tools:
                del self._tools[name]
                logger.info("Unregistered tool: '%s'", name)
                return True
            return False

    def get_tool(self, name: str) -> Optional[Tool]:
        """Look up a tool by its registered identifier."""
        with self._lock:
            return self._tools.get(name)

    def has_tool(self, name: str) -> bool:
        """Check if a tool with given identifier is registered."""
        with self._lock:
            return name in self._tools

    def list_tools(self) -> List[ToolDefinition]:
        """List all registered tool definitions in deterministic order."""
        with self._lock:
            return [tool.definition for _, tool in sorted(self._tools.items())]

    def clear(self) -> None:
        """Unregister all tools. Primarily used in test fixtures."""
        with self._lock:
            self._tools.clear()
            logger.debug("Tool registry cleared.")
