"""Confirmation-gated macOS desktop actions.

These tools intentionally support a small, auditable set of actions. They are
registered behind :class:`PermissionLevel.CONFIRM`, so they can only run after
the interface has shown the exact requested action and the user approves it.
"""
from __future__ import annotations

import asyncio
import platform
from pathlib import Path
from typing import Any

from atlas.core.tools.base import PermissionLevel, Tool, ToolResult


class OpenApplicationTool(Tool):
    """Open a named macOS application through Launch Services."""

    def __init__(self) -> None:
        self.name = "desktop.open_application"
        self.description = "Open a named application on this Mac after the user confirms."
        self.parameters = {
            "type": "object",
            "properties": {"app": {"type": "string", "description": "Application name."}},
            "required": ["app"],
            "additionalProperties": False,
        }
        self.permission = PermissionLevel.CONFIRM

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        app = arguments.get("app")
        if not isinstance(app, str) or not app.strip():
            raise ValueError("'app' must be a non-empty string")
        if len(app.strip()) > 120:
            raise ValueError("'app' must be 120 characters or fewer")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if platform.system() != "Darwin":
            return ToolResult(False, "", error="Opening applications is only implemented on macOS.")
        app = arguments["app"].strip()
        return await _run_open(["open", "-a", app], f"Could not open application: {app}", {"app": app})


class OpenFileTool(Tool):
    """Open one existing regular file without following symlinks."""

    def __init__(self) -> None:
        self.name = "desktop.open_file"
        self.description = "Open one existing local file on this Mac after the user confirms."
        self.parameters = {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Path of the file to open."}},
            "required": ["path"],
            "additionalProperties": False,
        }
        self.permission = PermissionLevel.CONFIRM

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("'path' must be a non-empty string")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if platform.system() != "Darwin":
            return ToolResult(False, "", error="Opening files is only implemented on macOS.")
        path = Path(arguments["path"]).expanduser()
        if path.is_symlink():
            return ToolResult(False, "", error="Refusing to open a symlink.")
        if not path.exists():
            return ToolResult(False, "", error=f"Path does not exist: {path}")
        if not path.is_file():
            return ToolResult(False, "", error=f"Path is not a regular file: {path}")
        resolved = path.resolve()
        return await _run_open(
            ["open", str(resolved)], f"Could not open file: {resolved}", {"path": str(resolved)}
        )


class CopyToClipboardTool(Tool):
    """Copy explicitly provided text to the macOS clipboard."""

    _MAX_TEXT_LENGTH = 10_000

    def __init__(self) -> None:
        self.name = "desktop.copy_to_clipboard"
        self.description = "Copy user-provided text to the macOS clipboard after the user confirms."
        self.parameters = {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text to copy."}},
            "required": ["text"],
            "additionalProperties": False,
        }
        self.permission = PermissionLevel.CONFIRM

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        text = arguments.get("text")
        if not isinstance(text, str) or not text:
            raise ValueError("'text' must be a non-empty string")
        if len(text) > self._MAX_TEXT_LENGTH:
            raise ValueError(f"'text' must be {self._MAX_TEXT_LENGTH} characters or fewer")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if platform.system() != "Darwin":
            return ToolResult(False, "", error="Clipboard copy is only implemented on macOS.")
        process = await asyncio.create_subprocess_exec(
            "pbcopy", stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(process.communicate(arguments["text"].encode()), timeout=5)
        if process.returncode != 0:
            return ToolResult(False, "", error="Could not copy text to the clipboard.")
        return ToolResult(
            True,
            "Copied text to the clipboard.",
            data={"characters": len(arguments["text"])},
        )


async def _run_open(command: list[str], failure: str, data: dict[str, str]) -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    await asyncio.wait_for(process.communicate(), timeout=10)
    if process.returncode != 0:
        return ToolResult(False, "", error=failure)
    return ToolResult(True, "Opened successfully.", data=data)
