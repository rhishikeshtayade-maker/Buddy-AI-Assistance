"""BUDDY "Start BUDDY when I sign in" support.

Uses the standard, user-visible per-user Run key:

    HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run  ->  "BUDDY"

This entry appears in Task Manager -> Startup apps and in Windows Settings ->
Apps -> Startup, where the user can also disable it. BUDDY:

* never writes the entry unless the user explicitly opts in;
* removes the entry when the user opts out;
* uses no services, scheduled tasks, hidden files or other persistence;
* launches the GUI interpreter directly (no cmd/PowerShell wrapper).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional, Protocol

logger = logging.getLogger("buddy.desktop.startup")

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE_NAME = "BUDDY"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class RunKeyBackend(Protocol):
    """Minimal registry abstraction (injectable for tests)."""

    def read(self, name: str) -> Optional[str]: ...

    def write(self, name: str, value: str) -> None: ...

    def delete(self, name: str) -> None: ...


class WinRegRunKeyBackend:
    """HKCU Run-key backend using the standard library ``winreg`` module."""

    def __init__(self, key_path: str = RUN_KEY_PATH) -> None:
        import winreg  # Windows only; raises ImportError elsewhere

        self._winreg = winreg
        self._key_path = key_path

    def read(self, name: str) -> Optional[str]:
        wr = self._winreg
        try:
            with wr.OpenKey(wr.HKEY_CURRENT_USER, self._key_path, 0, wr.KEY_READ) as key:
                value, _ = wr.QueryValueEx(key, name)
                return str(value)
        except FileNotFoundError:
            return None

    def write(self, name: str, value: str) -> None:
        wr = self._winreg
        with wr.CreateKeyEx(wr.HKEY_CURRENT_USER, self._key_path, 0, wr.KEY_SET_VALUE) as key:
            wr.SetValueEx(key, name, 0, wr.REG_SZ, value)

    def delete(self, name: str) -> None:
        wr = self._winreg
        try:
            with wr.OpenKey(wr.HKEY_CURRENT_USER, self._key_path, 0, wr.KEY_SET_VALUE) as key:
                wr.DeleteValue(key, name)
        except FileNotFoundError:
            pass


class InMemoryRunKeyBackend:
    """Test double for the Run key."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def read(self, name: str) -> Optional[str]:
        return self.values.get(name)

    def write(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def gui_interpreter() -> Path:
    """Return pythonw.exe next to the current interpreter when available (no console window)."""
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return candidate if candidate.exists() else exe


def build_launch_command(interpreter: Optional[Path] = None, project_root: Optional[Path] = None) -> str:
    """Build the quoted launch command stored in the Run key.

    Example: ``"C:\\Python313\\pythonw.exe" "D:\\BUDDY\\app\\desktop\\__main__.py" --tray``
    """
    interp = interpreter or gui_interpreter()
    root = project_root or PROJECT_ROOT
    entry = root / "app" / "desktop" / "__main__.py"
    return f'"{interp}" "{entry}" --tray'


class LoginStartupManager:
    """Explicit opt-in management of the per-user login startup entry."""

    def __init__(self, backend: Optional[RunKeyBackend] = None, command: Optional[str] = None) -> None:
        self._backend = backend
        self._command = command

    def _get_backend(self) -> Optional[RunKeyBackend]:
        if self._backend is None:
            try:
                self._backend = WinRegRunKeyBackend()
            except ImportError:
                logger.info("Login startup is only supported on Windows.")
                return None
        return self._backend

    @property
    def supported(self) -> bool:
        return self._get_backend() is not None

    @property
    def command(self) -> str:
        return self._command or build_launch_command()

    def is_enabled(self) -> bool:
        backend = self._get_backend()
        if backend is None:
            return False
        try:
            return backend.read(RUN_VALUE_NAME) is not None
        except OSError as err:
            logger.warning("Could not read login startup entry: %s", err)
            return False

    def enable(self) -> bool:
        """Create/refresh the startup entry. Call only after explicit user opt-in."""
        backend = self._get_backend()
        if backend is None:
            return False
        try:
            backend.write(RUN_VALUE_NAME, self.command)
            logger.info("Login startup enabled by user (HKCU Run\\%s).", RUN_VALUE_NAME)
            return True
        except OSError as err:
            logger.error("Could not enable login startup: %s", err)
            return False

    def disable(self) -> bool:
        backend = self._get_backend()
        if backend is None:
            return True
        try:
            backend.delete(RUN_VALUE_NAME)
            logger.info("Login startup disabled by user.")
            return True
        except OSError as err:
            logger.error("Could not disable login startup: %s", err)
            return False

    def apply(self, enabled: bool) -> bool:
        """Synchronise the Run entry with the user's setting."""
        return self.enable() if enabled else self.disable()
