"""BUDDY Application Management Tools.

Provides strictly controlled, allowlisted application launching, enumeration,
and graceful termination. Never executes arbitrary shell commands or untrusted binaries.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional

import psutil

from app.tools.base import Tool
from app.tools.models import (
    ToolDefinition,
    ToolPermissionLevel,
    ToolRiskLevel,
)

logger = logging.getLogger("buddy.tools.applications")

# Explicit, immutable application allowlist mapping friendly aliases to executable names
APPROVED_APPLICATIONS: Dict[str, str] = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "mspaint": "mspaint.exe",
    "explorer": "explorer.exe",
}


def _resolve_binary(executable_name: str) -> Optional[str]:
    """Resolve an approved executable from standard system paths."""
    # Look in System32 first for Windows security
    if os.name == "nt":
        sys32 = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", executable_name)
        if os.path.exists(sys32):
            return sys32
    return shutil.which(executable_name)


class AppListTool(Tool):
    """Enumerates running processes safely without leaking command lines, tokens, or env vars."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="app.list",
            description="List active desktop applications and processes safely (name, PID, status).",
            input_schema={},
            output_schema={
                "type": "object",
                "properties": {
                    "applications": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "pid": {"type": "integer"},
                                "status": {"type": "string"},
                            },
                        },
                    },
                    "count": {"type": "integer"},
                },
            },
            risk_level=ToolRiskLevel.SAFE,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            requires_authentication=False,
            timeout_seconds=5.0,
        )

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        apps: List[Dict[str, Any]] = []
        for proc in psutil.process_iter(attrs=["pid", "name", "status"]):
            try:
                info = proc.info
                name = info.get("name")
                if name:
                    apps.append({
                        "name": name,
                        "pid": info.get("pid"),
                        "status": info.get("status"),
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return {
            "applications": apps[:100],  # Bound return count
            "count": len(apps),
        }

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        return isinstance(raw_output, dict) and "applications" in raw_output and "count" in raw_output


class AppOpenTool(Tool):
    """Launches an approved application from the explicit allowlist."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="app.open",
            description=(
                "Launch an allowlisted application. Approved applications: "
                + ", ".join(sorted(APPROVED_APPLICATIONS.keys()))
            ),
            input_schema={
                "type": "object",
                "required": ["application"],
                "properties": {
                    "application": {
                        "type": "string",
                        "enum": sorted(list(APPROVED_APPLICATIONS.keys())),
                        "description": "Approved application identifier (e.g. 'notepad', 'calculator')",
                    },
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "application": {"type": "string"},
                    "executable": {"type": "string"},
                    "launched": {"type": "boolean"},
                },
            },
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            requires_authentication=False,
            timeout_seconds=10.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        app_name = str(arguments.get("application", "")).strip().lower()
        if not app_name:
            raise ValueError("Argument 'application' is required.")

        if app_name not in APPROVED_APPLICATIONS:
            raise ValueError(
                f"Application '{app_name}' is not in the approved allowlist: {sorted(APPROVED_APPLICATIONS.keys())}."
            )

        return {"application": app_name}

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        app_name = arguments["application"]
        exe_name = APPROVED_APPLICATIONS[app_name]
        binary_path = _resolve_binary(exe_name)

        if not binary_path:
            raise RuntimeError(f"Executable '{exe_name}' could not be located on the system.")

        logger.info("Launching approved application '%s' via binary '%s'", app_name, binary_path)

        # STRICT SECURITY: Never use shell=True. Pass exact binary path as sole argument in list.
        subprocess.Popen([binary_path], close_fds=True)

        return {
            "application": app_name,
            "executable": exe_name,
            "launched": True,
        }

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        if not isinstance(raw_output, dict) or not raw_output.get("launched"):
            return False

        app_name = arguments["application"]
        exe_name = APPROVED_APPLICATIONS[app_name].lower()

        # Give process up to 3 seconds to appear in process list
        for _ in range(6):
            await asyncio.sleep(0.5)
            for proc in psutil.process_iter(attrs=["name"]):
                try:
                    pname = (proc.info.get("name") or "").lower()
                    if pname == exe_name or pname.startswith(app_name):
                        logger.info("Verified active process for '%s' (image='%s')", app_name, pname)
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        logger.warning("Verification failed: process for '%s' not detected within timeout.", app_name)
        return False


class AppCloseTool(Tool):
    """Gracefully terminates an approved application from the allowlist."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="app.close",
            description="Close all running instances of an allowlisted application.",
            input_schema={
                "type": "object",
                "required": ["application"],
                "properties": {
                    "application": {
                        "type": "string",
                        "enum": sorted(list(APPROVED_APPLICATIONS.keys())),
                        "description": "Approved application identifier (e.g. 'notepad', 'calculator')",
                    },
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "application": {"type": "string"},
                    "terminated_count": {"type": "integer"},
                },
            },
            risk_level=ToolRiskLevel.MODERATE,
            permission_level=ToolPermissionLevel.CONFIRM,
            requires_confirmation=True,
            requires_authentication=False,
            timeout_seconds=10.0,
        )

    async def validate_input(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        app_name = str(arguments.get("application", "")).strip().lower()
        if not app_name:
            raise ValueError("Argument 'application' is required.")

        if app_name not in APPROVED_APPLICATIONS:
            raise ValueError(
                f"Application '{app_name}' is not in the approved allowlist: {sorted(APPROVED_APPLICATIONS.keys())}."
            )

        return {"application": app_name}

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        app_name = arguments["application"]
        exe_name = APPROVED_APPLICATIONS[app_name].lower()
        terminated_count = 0

        for proc in psutil.process_iter(attrs=["pid", "name"]):
            try:
                pname = (proc.info.get("name") or "").lower()
                if pname == exe_name or pname.startswith(app_name):
                    proc.terminate()
                    terminated_count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        logger.info("Terminated %d processes matching '%s'", terminated_count, app_name)
        return {
            "application": app_name,
            "terminated_count": terminated_count,
        }

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        if not isinstance(raw_output, dict):
            return False

        app_name = arguments["application"]
        exe_name = APPROVED_APPLICATIONS[app_name].lower()

        # Brief wait for process termination to register
        await asyncio.sleep(0.5)

        for proc in psutil.process_iter(attrs=["name"]):
            try:
                pname = (proc.info.get("name") or "").lower()
                if pname == exe_name:
                    logger.warning("Verification failed: process '%s' still running.", exe_name)
                    return False
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return True
