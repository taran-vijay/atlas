"""Safe, read-only tools for interacting with the local system."""
from __future__ import annotations

import platform
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar

from atlas.core.tools.base import PermissionLevel, Tool, ToolResult


class GetTimeTool(Tool):
    name = "system.get_time"
    description = "Return the current local date and time of the machine running Atlas."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    permission = PermissionLevel.READ_ONLY

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        if arguments:
            raise ValueError("system.get_time does not accept arguments")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        now = datetime.now().astimezone()
        content = now.strftime("%A, %B %d, %Y at %I:%M:%S %p %Z")
        return ToolResult(
            success=True,
            content=content,
            data={"iso": now.isoformat(), "timezone": str(now.tzinfo)},
        )


class GetSystemInfoTool(Tool):
    name = "system.get_system_info"
    description = "Return basic operating system and hardware information for the machine running Atlas."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    permission = PermissionLevel.READ_ONLY

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        if arguments:
            raise ValueError("system.get_system_info does not accept arguments")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        info = {
            "operating_system": platform.system(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor() or "unknown",
            "python_version": platform.python_version(),
        }
        content = (
            f"OS: {info['operating_system']} {info['os_version']}; "
            f"architecture: {info['machine']}; processor: {info['processor']}; "
            f"Python: {info['python_version']}"
        )
        return ToolResult(success=True, content=content, data=info)


class ListDirectoryTool(Tool):
    name = "filesystem.list_directory"
    description = "List the immediate contents of a local directory. This is read-only and does not modify files."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Absolute or user-home-relative directory path to list.",
            }
        },
        "required": ["path"],
        "additionalProperties": False,
    }
    permission = PermissionLevel.READ_ONLY

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("'path' must be a non-empty string")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path = Path(arguments["path"]).expanduser()
        if not path.exists():
            return ToolResult(success=False, content="", error=f"Path does not exist: {path}")
        if not path.is_dir():
            return ToolResult(success=False, content="", error=f"Path is not a directory: {path}")

        entries = sorted(path.iterdir(), key=lambda entry: (not entry.is_dir(), entry.name.lower()))
        data = {
            "path": str(path),
            "entries": [
                {"name": entry.name, "type": "directory" if entry.is_dir() else "file"}
                for entry in entries
            ],
        }
        if not entries:
            content = f"Directory {path} is empty."
        else:
            lines = [
                f"{'[DIR]' if entry.is_dir() else '[FILE]'} {entry.name}"
                for entry in entries
            ]
            content = f"Contents of {path}:\n" + "\n".join(lines)
        return ToolResult(success=True, content=content, data=data)
