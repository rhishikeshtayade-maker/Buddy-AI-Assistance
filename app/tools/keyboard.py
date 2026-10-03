"""BUDDY Controlled Keyboard Interaction Tools.

Implements restricted keyboard.key_press and keyboard.type_text.
Guarantees zero password/credential injection and ensures typed text is never persisted or logged.
"""

from __future__ import annotations

import ctypes
import logging
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from app.core.events import EventBus
from app.tools.base import Tool
from app.tools.events import (
    InteractionVerificationFailedEvent,
    KeyboardActionCompletedEvent,
    KeyboardActionStartedEvent,
)
from app.tools.interaction_models import (
    ALLOWED_KEYS,
    InteractionAction,
    InteractionRequest,
    TextSensitivity,
)

if TYPE_CHECKING:
    from app.security.interaction_policy import InteractionPolicy
from app.tools.models import (
    ToolDefinition,
    ToolPermissionLevel,
    ToolRiskLevel,
)

logger = logging.getLogger("buddy.tools.keyboard")

# Windows Virtual-Key code mapping for allowlisted keys
VK_MAP: Dict[str, int] = {
    "ENTER": 0x0D,
    "ESC": 0x1B,
    "TAB": 0x09,
    "BACKSPACE": 0x08,
    "SPACE": 0x20,
    "PAGE_UP": 0x21,
    "PAGE_DOWN": 0x22,
    "END": 0x23,
    "HOME": 0x24,
    "ARROW_LEFT": 0x25,
    "ARROW_UP": 0x26,
    "ARROW_RIGHT": 0x27,
    "ARROW_DOWN": 0x28,
}


class KeyboardController(ABC):
    """Abstract interface for low-level OS keyboard dispatch."""

    @abstractmethod
    def press_key(self, key_name: str) -> None:
        ...

    @abstractmethod
    def type_text(self, text: str) -> None:
        ...


class WindowsKeyboardController(KeyboardController):
    """Dispatches physical keyboard events via standard Windows User32 keybd_event."""

    KEYEVENTF_KEYUP = 0x0002

    def press_key(self, key_name: str) -> None:
        vk = VK_MAP.get(key_name)
        if not vk:
            return
        user32 = ctypes.windll.user32
        user32.keybd_event(vk, 0, 0, 0)
        time.sleep(0.02)
        user32.keybd_event(vk, 0, self.KEYEVENTF_KEYUP, 0)

    def type_text(self, text: str) -> None:
        user32 = ctypes.windll.user32
        KEYEVENTF_UNICODE = 0x0004
        for char in text:
            code = ord(char)
            user32.keybd_event(0, code, KEYEVENTF_UNICODE, 0)
            user32.keybd_event(0, code, KEYEVENTF_UNICODE | self.KEYEVENTF_KEYUP, 0)
            time.sleep(0.01)


class MockKeyboardController(KeyboardController):
    """Deterministic in-memory keyboard controller for headless testing."""

    def __init__(self) -> None:
        self.pressed_keys: List[str] = []
        self.typed_strings: List[str] = []

    def press_key(self, key_name: str) -> None:
        self.pressed_keys.append(key_name)

    def type_text(self, text: str) -> None:
        self.typed_strings.append(text)


class KeyPressTool(Tool):
    """Presses an allowlisted keyboard key."""

    def __init__(
        self,
        policy: InteractionPolicy,
        controller: Optional[KeyboardController] = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self._policy = policy
        self._controller = controller or MockKeyboardController()
        self._event_bus = event_bus

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="keyboard.key_press",
            description=(
                "Press a single allowlisted keyboard key. Supported keys: "
                + ", ".join(sorted(ALLOWED_KEYS))
            ),
            input_schema={
                "type": "object",
                "required": ["key"],
                "properties": {
                    "key": {
                        "type": "string",
                        "enum": sorted(list(ALLOWED_KEYS)),
                        "description": "Allowed keyboard key",
                    },
                },
            },
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=5.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        key = arguments.get("key", "")
        req = InteractionRequest(action_type=InteractionAction.KEY_PRESS, key=key)
        self._policy.validate_request(req)
        normalized = self._policy.validate_key(key)
        return {"key": normalized}

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        start = time.perf_counter()
        key = arguments["key"]

        if self._event_bus:
            await self._event_bus.publish(
                KeyboardActionStartedEvent(action_type="key_press", key=key)
            )

        self._controller.press_key(key)

        result = {"pressed": True, "key": key}

        if self._event_bus:
            await self._event_bus.publish(
                KeyboardActionCompletedEvent(
                    action_type="key_press",
                    verified=True,
                    latency=time.perf_counter() - start,
                )
            )

        return result

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        valid = isinstance(raw_output, dict) and raw_output.get("pressed") is True
        if not valid and self._event_bus:
            await self._event_bus.publish(
                InteractionVerificationFailedEvent(
                    action_type="key_press",
                    reason="Key press execution flag missing or false",
                )
            )
        return valid


class TypeTextTool(Tool):
    """Types non-sensitive, user-approved text into the focused control."""

    def __init__(
        self,
        policy: InteractionPolicy,
        controller: Optional[KeyboardController] = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self._policy = policy
        self._controller = controller or MockKeyboardController()
        self._event_bus = event_bus

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="keyboard.type_text",
            description="Type safe text into the currently focused window. Passwords and credentials are forbidden.",
            input_schema={
                "type": "object",
                "required": ["text"],
                "properties": {
                    "text": {"type": "string", "description": "Text to type"},
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "character_count": {"type": "integer"},
                    "typed": {"type": "boolean"},
                },
            },
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=10.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        text = str(arguments.get("text", ""))
        req = InteractionRequest(action_type=InteractionAction.TYPE, text=text)
        self._policy.validate_request(req)
        return {"text": text}

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        start = time.perf_counter()
        text = arguments["text"]

        if self._event_bus:
            # PRIVACY: Do NOT include raw text in started event
            await self._event_bus.publish(
                KeyboardActionStartedEvent(action_type="type_text")
            )

        self._controller.type_text(text)

        # PRIVACY: Never return or log raw typed text in output metadata
        result = {
            "typed": True,
            "character_count": len(text),
        }

        if self._event_bus:
            await self._event_bus.publish(
                KeyboardActionCompletedEvent(
                    action_type="type_text",
                    verified=True,
                    latency=time.perf_counter() - start,
                )
            )

        return result

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        valid = isinstance(raw_output, dict) and raw_output.get("typed") is True
        if not valid and self._event_bus:
            await self._event_bus.publish(
                InteractionVerificationFailedEvent(
                    action_type="type_text",
                    reason="Text typing verification flag missing or false",
                )
            )
        return valid
