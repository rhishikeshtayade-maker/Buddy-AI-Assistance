"""BUDDY Foreground Application Observer.

Detects the currently focused application identity, process name, and window title
using narrow Windows Win32 APIs with complete failure isolation.

STRICT PRIVACY GUARANTEES:
- NO keystroke monitoring
- NO typed text capture
- NO clipboard monitoring
- NO continuous screenshots
- Sensitive windows automatically have their titles stripped
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from typing import Callable, Optional

import psutil

from app.context_awareness.config import ContextAwarenessConfig
from app.context_awareness.models import (
    ForegroundAppInfo,
    SensitivityLevel,
    TriggerType,
)
from app.context_awareness.observers import BaseObserver
from app.context_awareness.permissions import ContextPermissionGuard, ObserverPermissionType
from app.context_awareness.privacy import PrivacyGuard
from app.core.events import EventBus
from app.core.logging import get_logger

logger = get_logger("context.foreground")


class ForegroundObserver(BaseObserver):
    """Monitors currently focused application with Win32 API and failure isolation."""

    def __init__(
        self,
        config: ContextAwarenessConfig,
        permission_guard: ContextPermissionGuard,
        privacy_guard: PrivacyGuard,
        event_bus: Optional[EventBus] = None,
        on_app_change: Optional[Callable[[ForegroundAppInfo, TriggerType], None]] = None,
    ) -> None:
        super().__init__(
            name="foreground",
            permission_type=ObserverPermissionType.FOREGROUND,
            config=config,
            permission_guard=permission_guard,
            event_bus=event_bus,
        )
        self.privacy_guard = privacy_guard
        self.on_app_change = on_app_change

        self._current_info: Optional[ForegroundAppInfo] = None
        self._simulated_info: Optional[ForegroundAppInfo] = None

    @property
    def current_app(self) -> Optional[ForegroundAppInfo]:
        """Get the last detected foreground application info."""
        if self._simulated_info is not None:
            return self._query_foreground()
        return self._current_info

    def set_simulated_app(
        self,
        process_name: str,
        app_identity: str,
        window_title: Optional[str] = None,
        pid: Optional[int] = 1234,
        is_sensitive: bool = False,
    ) -> None:
        """Testing utility: simulate an active application context."""
        self._simulated_info = ForegroundAppInfo(
            process_name=process_name,
            app_identity=app_identity,
            window_title=window_title,
            pid=pid,
            is_sensitive=is_sensitive,
        )
        self._current_info = self._query_foreground()

    def clear_simulated_app(self) -> None:
        """Clear test simulation."""
        self._simulated_info = None

    def _get_active_window_windows(self) -> ForegroundAppInfo:
        """Call narrow Windows APIs to retrieve foreground hwnd, pid, process name, and window title."""
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ForegroundAppInfo(
                process_name="idle.exe",
                app_identity="Desktop / Idle",
                window_title="Desktop",
                pid=0,
            )

        # 1. Get process ID
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_id = pid.value

        # 2. Get process name
        process_name = "unknown.exe"
        try:
            proc = psutil.Process(process_id)
            process_name = proc.name()
        except Exception:
            pass

        # 3. Get window title text
        length = user32.GetWindowTextLengthW(hwnd)
        window_title: Optional[str] = None
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            window_title = buff.value.strip()

        # 4. Map application identity
        app_identity = process_name.replace(".exe", "").title()
        if "code" in process_name.lower():
            app_identity = "Visual Studio Code"
        elif "chrome" in process_name.lower():
            app_identity = "Google Chrome"
        elif "firefox" in process_name.lower():
            app_identity = "Mozilla Firefox"
        elif "msedge" in process_name.lower():
            app_identity = "Microsoft Edge"
        elif "notepad" in process_name.lower():
            app_identity = "Notepad"
        elif "explorer" in process_name.lower():
            app_identity = "Windows Explorer"
        elif "cmd" in process_name.lower() or "powershell" in process_name.lower():
            app_identity = "Terminal"

        is_sensitive = self.privacy_guard.is_sensitive_context(
            foreground=ForegroundAppInfo(
                process_name=process_name,
                app_identity=app_identity,
                window_title=window_title,
                pid=process_id,
            ),
            window_title=window_title,
        )

        if is_sensitive:
            window_title = "[REDACTED_SENSITIVE_CONTEXT]"

        return ForegroundAppInfo(
            process_name=process_name,
            app_identity=app_identity,
            window_title=window_title,
            pid=process_id,
            is_sensitive=is_sensitive,
        )

    def _query_foreground(self) -> ForegroundAppInfo:
        """Query active window via simulation or native platform API."""
        if self._simulated_info is not None:
            info = self._simulated_info
            if self.privacy_guard.is_sensitive_context(foreground=info, window_title=info.window_title):
                return ForegroundAppInfo(
                    process_name=info.process_name,
                    app_identity=info.app_identity,
                    window_title="[REDACTED_SENSITIVE_CONTEXT]",
                    pid=info.pid,
                    is_sensitive=True,
                )
            return info

        if sys.platform == "win32":
            try:
                return self._get_active_window_windows()
            except Exception as e:
                logger.debug("Win32 active window call failed: %s", e)

        # Fallback for non-windows or mock environments
        return ForegroundAppInfo(
            process_name="generic.exe",
            app_identity="Default Application",
            window_title="Workspace",
            pid=1000,
        )

    async def poll(self) -> ForegroundAppInfo:
        """Poll foreground application and detect focus transitions."""
        info = self._query_foreground()
        prev = self._current_info
        self._current_info = info

        # Detect transition
        if prev is None or prev.process_name != info.process_name or prev.window_title != info.window_title:
            trigger_type = TriggerType.AppFocused
            if prev is None or prev.process_name != info.process_name:
                trigger_type = TriggerType.AppOpened

            if self.on_app_change:
                try:
                    self.on_app_change(info, trigger_type)
                except Exception as e:
                    logger.warning("Error in on_app_change callback: %s", e)

        return info
