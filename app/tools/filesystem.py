"""BUDDY Sandboxed Filesystem Tools.

Provides strictly controlled file search, read, creation, copy, rename, and move
within authorized user directory roots, validated against PathPolicy.
"""

from __future__ import annotations

import fnmatch
import hashlib
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.security.path_policy import PathPolicy
from app.tools.base import Tool
from app.tools.models import (
    ToolDefinition,
    ToolPermissionLevel,
    ToolRiskLevel,
)

logger = logging.getLogger("buddy.tools.filesystem")

MAX_READ_BYTES = 1024 * 1024  # 1 MB maximum read size


class FileSearchTool(Tool):
    """Searches for files within approved directories matching a pattern."""

    def __init__(self, path_policy: Optional[PathPolicy] = None) -> None:
        self._policy = path_policy or PathPolicy()

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file.search",
            description="Search for files matching a pattern within an authorized root directory.",
            input_schema={
                "type": "object",
                "required": ["pattern"],
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (e.g. '*.txt')"},
                    "directory": {"type": "string", "description": "Optional search directory within allowed roots"},
                    "max_results": {"type": "integer", "default": 50},
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "results": {"type": "array", "items": {"type": "string"}},
                    "count": {"type": "integer"},
                },
            },
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            requires_authentication=False,
            timeout_seconds=10.0,
        )

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        pattern = arguments.get("pattern", "*")
        dir_arg = arguments.get("directory")
        max_results = min(100, int(arguments.get("max_results", 50)))

        # Determine target search roots
        search_roots: List[Path] = []
        if dir_arg:
            target_dir = self._policy.validate_path(dir_arg)
            if not target_dir.is_dir():
                raise NotADirectoryError(f"Target path '{dir_arg}' is not a directory.")
            search_roots.append(target_dir)
        else:
            search_roots = [r for r in self._policy.allowed_roots if r.exists() and r.is_dir()]

        matches: List[str] = []
        for root in search_roots:
            for dirpath, _, filenames in os.walk(root):
                for filename in filenames:
                    if fnmatch.fnmatch(filename, pattern):
                        full_path = Path(dirpath) / filename
                        # Re-verify individual path against policy
                        if self._policy.is_path_allowed(full_path):
                            matches.append(str(full_path))
                            if len(matches) >= max_results:
                                break
                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results:
                break

        return {
            "results": matches,
            "count": len(matches),
        }

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        if not isinstance(raw_output, dict) or "results" not in raw_output:
            return False
        # Verify that all results are allowed paths
        for path_str in raw_output["results"]:
            if not self._policy.is_path_allowed(path_str):
                return False
        return True


class FileReadTool(Tool):
    """Reads file contents from within approved directories."""

    def __init__(self, path_policy: Optional[PathPolicy] = None) -> None:
        self._policy = path_policy or PathPolicy()

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file.read",
            description="Read text contents of a file within authorized directory roots.",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative file path to read"},
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "size_bytes": {"type": "integer"},
                },
            },
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            requires_authentication=False,
            timeout_seconds=5.0,
        )

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        raw_path = arguments.get("path")
        valid_path = self._policy.validate_path(raw_path)

        if not valid_path.is_file():
            raise FileNotFoundError(f"File not found: '{valid_path}'")

        size = valid_path.stat().st_size
        if size > MAX_READ_BYTES:
            raise ValueError(f"File size ({size} bytes) exceeds maximum permitted read limit ({MAX_READ_BYTES} bytes).")

        content = valid_path.read_text(encoding="utf-8", errors="replace")
        return {
            "path": str(valid_path),
            "content": content,
            "size_bytes": len(content.encode("utf-8")),
        }

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        if not isinstance(raw_output, dict):
            return False
        return "content" in raw_output and "size_bytes" in raw_output


class FileCreateTool(Tool):
    """Creates a new file within approved directories."""

    def __init__(self, path_policy: Optional[PathPolicy] = None) -> None:
        self._policy = path_policy or PathPolicy()

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file.create",
            description="Create a new file with specified content within an authorized directory.",
            input_schema={
                "type": "object",
                "required": ["path", "content"],
                "properties": {
                    "path": {"type": "string", "description": "File path to create"},
                    "content": {"type": "string", "description": "Text content to write"},
                    "overwrite": {"type": "boolean", "default": False},
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "size_bytes": {"type": "integer"},
                    "sha256": {"type": "string"},
                },
            },
            risk_level=ToolRiskLevel.LOW,
            permission_level=ToolPermissionLevel.NONE,
            requires_confirmation=False,
            requires_authentication=False,
            timeout_seconds=5.0,
        )

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        raw_path = arguments.get("path")
        content = str(arguments.get("content", ""))
        overwrite = bool(arguments.get("overwrite", False))

        valid_path = self._policy.validate_path(raw_path, write=True)

        if valid_path.exists() and not overwrite:
            raise FileExistsError(f"File already exists and overwrite is False: '{valid_path}'")

        valid_path.parent.mkdir(parents=True, exist_ok=True)
        valid_path.write_text(content, encoding="utf-8")

        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        size = valid_path.stat().st_size

        return {
            "path": str(valid_path),
            "size_bytes": size,
            "sha256": digest,
        }

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        if not isinstance(raw_output, dict):
            return False

        path_str = raw_output.get("path")
        if not path_str:
            return False

        p = Path(path_str)
        if not p.is_file():
            return False

        # Verify content hash matches
        actual_hash = hashlib.sha256(p.read_bytes()).hexdigest()
        return actual_hash == raw_output.get("sha256")


class FileRenameTool(Tool):
    """Renames a file within approved directories."""

    def __init__(self, path_policy: Optional[PathPolicy] = None) -> None:
        self._policy = path_policy or PathPolicy()

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file.rename",
            description="Rename a file within authorized directory roots.",
            input_schema={
                "type": "object",
                "required": ["source_path", "destination_path"],
                "properties": {
                    "source_path": {"type": "string"},
                    "destination_path": {"type": "string"},
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "source_path": {"type": "string"},
                    "destination_path": {"type": "string"},
                    "renamed": {"type": "boolean"},
                },
            },
            risk_level=ToolRiskLevel.MODERATE,
            permission_level=ToolPermissionLevel.CONFIRM,
            requires_confirmation=True,
            requires_authentication=False,
            timeout_seconds=5.0,
        )

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        src = self._policy.validate_path(arguments.get("source_path"), write=True)
        dst = self._policy.validate_path(arguments.get("destination_path"), write=True)

        if not src.exists():
            raise FileNotFoundError(f"Source file not found: '{src}'")
        if dst.exists():
            raise FileExistsError(f"Destination path already exists: '{dst}'")

        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)

        return {
            "source_path": str(src),
            "destination_path": str(dst),
            "renamed": True,
        }

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        if not isinstance(raw_output, dict):
            return False
        src = Path(raw_output["source_path"])
        dst = Path(raw_output["destination_path"])
        return not src.exists() and dst.exists()


class FileCopyTool(Tool):
    """Copies a file within approved directories."""

    def __init__(self, path_policy: Optional[PathPolicy] = None) -> None:
        self._policy = path_policy or PathPolicy()

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file.copy",
            description="Copy a file to a new location within authorized directory roots.",
            input_schema={
                "type": "object",
                "required": ["source_path", "destination_path"],
                "properties": {
                    "source_path": {"type": "string"},
                    "destination_path": {"type": "string"},
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "source_path": {"type": "string"},
                    "destination_path": {"type": "string"},
                    "copied": {"type": "boolean"},
                },
            },
            risk_level=ToolRiskLevel.MODERATE,
            permission_level=ToolPermissionLevel.CONFIRM,
            requires_confirmation=True,
            requires_authentication=False,
            timeout_seconds=10.0,
        )

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        src = self._policy.validate_path(arguments.get("source_path"), write=False)
        dst = self._policy.validate_path(arguments.get("destination_path"), write=True)

        if not src.is_file():
            raise FileNotFoundError(f"Source file not found: '{src}'")
        if dst.exists():
            raise FileExistsError(f"Destination path already exists: '{dst}'")

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

        return {
            "source_path": str(src),
            "destination_path": str(dst),
            "copied": True,
        }

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        if not isinstance(raw_output, dict):
            return False
        src = Path(raw_output["source_path"])
        dst = Path(raw_output["destination_path"])
        return dst.is_file() and dst.stat().st_size == src.stat().st_size


class FileMoveTool(Tool):
    """Moves a file within approved directories."""

    def __init__(self, path_policy: Optional[PathPolicy] = None) -> None:
        self._policy = path_policy or PathPolicy()

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="file.move",
            description="Move a file to a new location within authorized directory roots.",
            input_schema={
                "type": "object",
                "required": ["source_path", "destination_path"],
                "properties": {
                    "source_path": {"type": "string"},
                    "destination_path": {"type": "string"},
                },
            },
            output_schema={
                "type": "object",
                "properties": {
                    "source_path": {"type": "string"},
                    "destination_path": {"type": "string"},
                    "moved": {"type": "boolean"},
                },
            },
            risk_level=ToolRiskLevel.MODERATE,
            permission_level=ToolPermissionLevel.CONFIRM,
            requires_confirmation=True,
            requires_authentication=False,
            timeout_seconds=10.0,
        )

    async def execute(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        src = self._policy.validate_path(arguments.get("source_path"), write=True)
        dst = self._policy.validate_path(arguments.get("destination_path"), write=True)

        if not src.exists():
            raise FileNotFoundError(f"Source file not found: '{src}'")
        if dst.exists():
            raise FileExistsError(f"Destination path already exists: '{dst}'")

        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(src, dst)

        return {
            "source_path": str(src),
            "destination_path": str(dst),
            "moved": True,
        }

    async def verify(self, arguments: Dict[str, Any], raw_output: Any) -> bool:
        if not isinstance(raw_output, dict):
            return False
        src = Path(raw_output["source_path"])
        dst = Path(raw_output["destination_path"])
        return not src.exists() and dst.exists()
