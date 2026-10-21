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

        ctypes.set_last_error(0)
        # "Local\" scopes the mutex to the current logon session (per user).
        mutex_name = f"Local\\{self._name}"
        handle = kernel32.CreateMutexW(None, False, mutex_name)
        last_error = ctypes.get_last_error()
        if not handle:
            logger.error(
                "CreateMutexW failed for '%s' (Win32 error=%d); unable to acquire instance lock.",
                mutex_name,
                last_error,
            )
            return False
        if last_error == _ERROR_ALREADY_EXISTS:
            logger.info(
                "Named mutex '%s' already exists (Win32 error=183); another instance is currently running.",
                mutex_name,
            )
            kernel32.CloseHandle(handle)
            return False
        logger.debug("Named mutex '%s' acquired successfully (handle=%s).", mutex_name, handle)
        self._handle = handle
        self._kernel32 = kernel32
        return True

    def _acquire_lockfile(self) -> bool:  # pragma: no cover - non-Windows path
        import fcntl

        path = Path(tempfile.gettempdir()) / f"{self._name}.lock"
        try:
            fh = open(path, "a+")
        except OSError as e:
            logger.error("Failed to open lockfile '%s': %s", path, e)
            return False

        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            logger.info("Lockfile '%s' is locked by another process: %s", path, e)
            fh.close()
            return False

        fh.seek(0)
        fh.truncate()
        fh.write(str(os.getpid()))
        fh.flush()
        self._lock_file = fh
        logger.debug("Lockfile '%s' acquired successfully.", path)
        return True

    def release(self) -> None:
        if not self._acquired:
            return
        if self._handle is not None and getattr(self, "_kernel32", None) is not None:
            try:
                self._kernel32.CloseHandle(self._handle)
                logger.debug("Named mutex 'Local\\%s' handle closed.", self._name)
            except Exception as e:  # pragma: no cover
                logger.debug("CloseHandle exception: %s", e)
            self._handle = None
        if self._lock_file is not None:  # pragma: no cover - non-Windows path
            try:
                self._lock_file.close()
                logger.debug("Lockfile '%s.lock' closed.", self._name)
            except Exception as e:
                logger.debug("Lockfile close exception: %s", e)
            self._lock_file = None
        self._acquired = False

    def __enter__(self) -> "SingleInstanceGuard":
        self.acquire()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()
