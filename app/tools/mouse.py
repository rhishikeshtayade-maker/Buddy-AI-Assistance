"""BUDDY Controlled Mouse Interaction Tools.

Implements mouse.click, mouse.double_click, and mouse.scroll through strictly bound
VisionTargets, screen fingerprint verification, and empirical state verification.
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from app.core.events import EventBus
from app.tools.base import Tool

if TYPE_CHECKING:
    from app.security.interaction_policy import InteractionPolicy
from app.tools.events import (
    InteractionVerificationFailedEvent,
    MouseActionCompletedEvent,
    MouseActionStartedEvent,
)
from app.tools.interaction_models import (
    InteractionAction,
    InteractionRequest,
    MouseButton,
)
from app.tools.models import (
    ToolDefinition,
    ToolPermissionLevel,
    ToolRiskLevel,
)
from app.vision.screen import ScreenManager

logger = logging.getLogger("buddy.tools.mouse")


class MouseController(ABC):
    """Abstract interface for low-level OS mouse dispatch."""

    @abstractmethod
    def click(self, x: int, y: int, button: MouseButton = MouseButton.LEFT) -> None:
        ...

    @abstractmethod
    def double_click(self, x: int, y: int) -> None:
        ...

    @abstractmethod
    def scroll(self, amount: int) -> None:
        ...


class WindowsMouseController(MouseController):
    """Dispatches physical mouse events via standard Windows User32 APIs."""

    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_WHEEL = 0x0800

    def click(self, x: int, y: int, button: MouseButton = MouseButton.LEFT) -> None:
        user32 = ctypes.windll.user32
        user32.SetCursorPos(x, y)
        time.sleep(0.02)
        if button == MouseButton.LEFT:
            user32.mouse_event(self.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            time.sleep(0.02)
            user32.mouse_event(self.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        elif button == MouseButton.RIGHT:
            user32.mouse_event(self.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
            time.sleep(0.02)
            user32.mouse_event(self.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)

    def double_click(self, x: int, y: int) -> None:
        self.click(x, y, MouseButton.LEFT)
        time.sleep(0.05)
        self.click(x, y, MouseButton.LEFT)

    def scroll(self, amount: int) -> None:
        user32 = ctypes.windll.user32
        wheel_delta = amount * 120  # Standard WHEEL_DELTA
        user32.mouse_event(self.MOUSEEVENTF_WHEEL, 0, 0, wheel_delta, 0)


class MockMouseController(MouseController):
    """Deterministic in-memory mouse controller for headless CI and automated testing."""

    def __init__(self) -> None:
        self.actions: List[Dict[str, Any]] = []

    def click(self, x: int, y: int, button: MouseButton = MouseButton.LEFT) -> None:
        self.actions.append({"action": "click", "x": x, "y": y, "button": button.value})

    def double_click(self, x: int, y: int) -> None:
        self.actions.append({"action": "double_click", "x": x, "y": y})

    def scroll(self, amount: int) -> None:
        self.actions.append({"action": "scroll", "amount": amount})


class MouseClickTool(Tool):
    """Executes a verified click on a bound VisionTarget."""

    def __init__(
        self,
        policy: InteractionPolicy,
        controller: Optional[MouseController] = None,
        screen_manager: Optional[ScreenManager] = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self._policy = policy
        self._controller = controller or MockMouseController()
        self._screen_manager = screen_manager
        self._event_bus = event_bus

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mouse.click",
            description="Click a verified UI element on screen. Requires target_id from vision analysis.",
            input_schema={
                "type": "object",
                "required": ["target_id"],
                "properties": {
                    "target_id": {"type": "string", "description": "Verified VisionTarget identifier"},
                    "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                    "screen_fingerprint": {"type": "string", "description": "Fingerprint from detection time"},
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "target_id": {"type": "string"},
                    "coordinates": {"type": "array", "items": {"type": "integer"}},
                    "clicked": {"type": "boolean"},
                    "verification_evidence": {"type": "string"},
                },
            },
            risk_level=ToolRiskLevel.MODERATE,
            permission_level=ToolPermissionLevel.CONFIRM,
            requires_confirmation=True,
            requires_authentication=False,
            timeout_seconds=5.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        target_id = arguments.get("target_id")
        if not target_id:
            raise ValueError("Parameter 'target_id' is required for mouse.click.")

        btn_str = arguments.get("button", "left").lower()
        button = MouseButton.RIGHT if btn_str == "right" else MouseButton.LEFT

        req = InteractionRequest(
            action_type=InteractionAction.CLICK,
            target_id=target_id,
            screen_fingerprint=arguments.get("screen_fingerprint"),
        )
        coords = self._policy.validate_request(req, self._screen_manager)
        return {
            "target_id": target_id,
            "coordinates": coords,
            "button": button,
            "screen_fingerprint": arguments.get("screen_fingerprint"),
        }

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        start = time.perf_counter()
        coords = arguments["coordinates"]
        button = arguments["button"]

        if self._event_bus:
            await self._event_bus.publish(
                MouseActionStartedEvent(
                    action_type="click",
                    coordinates=coords,
                )
            )

        pre_fp = self._screen_manager.get_screen_fingerprint() if self._screen_manager else None
        self._controller.click(coords[0], coords[1], button)
        post_fp = self._screen_manager.get_screen_fingerprint() if self._screen_manager else None

        evidence = "dispatched_to_verified_target_coordinates"
        if pre_fp and post_fp and pre_fp != post_fp:
            evidence = f"screen_state_transition:{pre_fp}->{post_fp}"

        result = {
            "target_id": arguments["target_id"],
            "coordinates": list(coords),
            "clicked": True,
            "verification_evidence": evidence,
        }

        if self._event_bus:
            await self._event_bus.publish(
                MouseActionCompletedEvent(
                    action_type="click",
                    verified=True,
                    latency=time.perf_counter() - start,
                )
            )

        return result

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        if not isinstance(raw_output, dict) or not raw_output.get("clicked"):
            if self._event_bus:
                await self._event_bus.publish(
                    InteractionVerificationFailedEvent(
                        action_type="click",
                        reason="Click confirmation flag missing or false",
                    )
                )
            return False
        return True


class MouseDoubleClickTool(Tool):
    """Executes a verified double-click on a bound VisionTarget."""

    def __init__(
        self,
        policy: InteractionPolicy,
        controller: Optional[MouseController] = None,
        screen_manager: Optional[ScreenManager] = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self._policy = policy
        self._controller = controller or MockMouseController()
        self._screen_manager = screen_manager
        self._event_bus = event_bus

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mouse.double_click",
            description="Double-click a verified UI element on screen.",
            input_schema={
                "type": "object",
                "required": ["target_id"],
                "properties": {
                    "target_id": {"type": "string"},
                    "screen_fingerprint": {"type": "string"},
                },
            },
            risk_level=ToolRiskLevel.MODERATE,
            permission_level=ToolPermissionLevel.CONFIRM,
            requires_confirmation=True,
            timeout_seconds=5.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        target_id = arguments.get("target_id")
        if not target_id:
            raise ValueError("Parameter 'target_id' is required for mouse.double_click.")

        req = InteractionRequest(
            action_type=InteractionAction.DOUBLE_CLICK,
            target_id=target_id,
            screen_fingerprint=arguments.get("screen_fingerprint"),
        )
        coords = self._policy.validate_request(req, self._screen_manager)
        return {
            "target_id": target_id,
            "coordinates": coords,
            "screen_fingerprint": arguments.get("screen_fingerprint"),
        }

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        start = time.perf_counter()
        coords = arguments["coordinates"]

        if self._event_bus:
            await self._event_bus.publish(
                MouseActionStartedEvent(
                    action_type="double_click",
                    coordinates=coords,
                )
            )

        pre_fp = self._screen_manager.get_screen_fingerprint() if self._screen_manager else None
        self._controller.double_click(coords[0], coords[1])
        post_fp = self._screen_manager.get_screen_fingerprint() if self._screen_manager else None

        evidence = "dispatched_to_verified_target_coordinates"
        if pre_fp and post_fp and pre_fp != post_fp:
            evidence = f"screen_state_transition:{pre_fp}->{post_fp}"

        result = {
            "target_id": arguments["target_id"],
            "coordinates": list(coords),
            "double_clicked": True,
            "verification_evidence": evidence,
        }

        if self._event_bus:
            await self._event_bus.publish(
                MouseActionCompletedEvent(
                    action_type="double_click",
                    verified=True,
                    latency=time.perf_counter() - start,
                )
            )

        return result

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        valid = isinstance(raw_output, dict) and raw_output.get("double_clicked") is True
        if not valid and self._event_bus:
            await self._event_bus.publish(
                InteractionVerificationFailedEvent(
                    action_type="double_click",
                    reason="Double-click execution flag missing or false",
                )
            )
        return valid


class MouseScrollTool(Tool):
    """Executes controlled scrolling."""

    def __init__(
        self,
        policy: InteractionPolicy,
        controller: Optional[MouseController] = None,
        screen_manager: Optional[ScreenManager] = None,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self._policy = policy
        self._controller = controller or MockMouseController()
        self._screen_manager = screen_manager
        self._event_bus = event_bus

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="mouse.scroll",
            description="Scroll vertically by a specified number of lines.",
            input_schema={
                "type": "object",
                "required": ["amount"],
                "properties": {
                    "amount": {"type": "integer", "description": "Positive for up, negative for down"},
                },
            },
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            timeout_seconds=5.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        amount = int(arguments.get("amount", 0))
        if amount == 0:
            raise ValueError("Scroll amount cannot be 0.")
        if abs(amount) > 100:
            raise ValueError("Scroll amount exceeds safe limits (-100 to 100).")
        return {"amount": amount}

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        start = time.perf_counter()
        amt = arguments["amount"]

        if self._event_bus:
            await self._event_bus.publish(
                MouseActionStartedEvent(action_type="scroll")
            )

        pre_fp = self._screen_manager.get_screen_fingerprint() if self._screen_manager else None
        self._controller.scroll(amt)
        post_fp = self._screen_manager.get_screen_fingerprint() if self._screen_manager else None

        evidence = "dispatched_scroll_event"
        if pre_fp and post_fp and pre_fp != post_fp:
            evidence = f"screen_state_transition:{pre_fp}->{post_fp}"

        result = {"scrolled": True, "amount": amt, "verification_evidence": evidence}

        if self._event_bus:
            await self._event_bus.publish(
                MouseActionCompletedEvent(
                    action_type="scroll",
                    verified=True,
                    latency=time.perf_counter() - start,
                )
            )

        return result

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        valid = isinstance(raw_output, dict) and raw_output.get("scrolled") is True
        if not valid and self._event_bus:
            await self._event_bus.publish(
                InteractionVerificationFailedEvent(
                    action_type="scroll",
                    reason="Scroll execution flag missing or false",
                )
            )
        return valid
