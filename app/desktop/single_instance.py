"""BUDDY single-instance guard.

Prevents a second BUDDY desktop process from opening a competing microphone
stream. On Windows a per-user named mutex is used (released automatically by
the OS if the process dies). Elsewhere an exclusive lock file is used.
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("buddy.desktop.single_instance")

DEFAULT_INSTANCE_NAME = "BUDDY-Desktop-Assistant"
_ERROR_ALREADY_EXISTS = 183


class SingleInstanceGuard:
    """Acquire/release process-wide ownership of the BUDDY desktop runtime."""

    def __init__(self, name: str = DEFAULT_INSTANCE_NAME) -> None:
        self._name = name
        self._handle: Optional[Any] = None
        self._lock_file: Optional[Any] = None
        self._acquired = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def acquired(self) -> bool:
        return self._acquired

    def acquire(self) -> bool:
        """Return True if this process now owns the instance, False if another does."""
        if self._acquired:
            return True
        if sys.platform == "win32":
            self._acquired = self._acquire_mutex()
        else:
            self._acquired = self._acquire_lockfile()
        return self._acquired

    def _acquire_mutex(self) -> bool:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        # "Local\" scopes the mutex to the current logon session (per user).
        handle = kernel32.CreateMutexW(None, False, f"Local\\{self._name}")
        last_error = ctypes.get_last_error()
        if not handle:
            logger.error("CreateMutexW failed (error=%s); refusing to start a second runtime.", last_error)
            return False
        if last_error == _ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        self._handle = handle
        self._kernel32 = kernel32
        return True

    def _acquire_lockfile(self) -> bool:  # pragma: no cover - non-Windows path
        import fcntl

        path = Path(tempfile.gettempdir()) / f"{self._name}.lock"
        fh = open(path, "a+")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        self._lock_file = fh
        return True

    def release(self) -> None:
        if not self._acquired:
            return
        if self._handle is not None:
            try:
                self._kernel32.CloseHandle(self._handle)
            except Exception:  # pragma: no cover
                pass
            self._handle = None
        if self._lock_file is not None:  # pragma: no cover - non-Windows path
            try:
                self._lock_file.close()
            except Exception:
                pass
            self._lock_file = None
        self._acquired = False

    def __enter__(self) -> "SingleInstanceGuard":
        self.acquire()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()
