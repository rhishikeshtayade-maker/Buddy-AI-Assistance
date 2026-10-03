"""BUDDY Base Tool Interface.

Defines the abstract base contract that every executable tool must fulfill:
definition, input validation, execution, and empirical state verification.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from app.tools.models import ToolDefinition


class Tool(ABC):
    """Abstract Base Class for all BUDDY tools.

    Security & Correctness Guarantee:
    Execution alone does NOT imply success. Every tool MUST implement `verify()`
    which inspects true system state (e.g. process existence, file properties)
    before an operation can be reported as successful to the AI and user.
    """

    @property
    @abstractmethod
    def definition(self) -> ToolDefinition:
        """Return the immutable definition, schemas, and risk classification of this tool."""
        ...

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Validate invocation arguments against the tool's input contract.

        Subclasses may override to implement custom parameter checks.
        Default implementation returns arguments unmodified if valid.
        Raises ValueError or TypeError on invalid arguments.
        """
        return arguments

    @abstractmethod
    async def execute(self, arguments: Dict[str, Any]) -> Any:
        """Perform the requested action asynchronously.

        Args:
            arguments: Validated input arguments.

        Returns:
            Raw execution output/data.

        Raises:
            Exception: If tool execution encounters a runtime error.
        """
        ...

    @abstractmethod
    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        """Empirically inspect actual system state to verify the action succeeded.

        Args:
            arguments: The arguments passed into execution.
            raw_output: The return value from execute().

        Returns:
            True if system state confirms intended result; False otherwise.
        """
        ...
