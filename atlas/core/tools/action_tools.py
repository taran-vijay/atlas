"""Confirmation-gated macOS desktop actions.

These tools intentionally support a small, auditable set of actions. They are
registered behind :class:`PermissionLevel.CONFIRM`, so they can only run after
the interface has shown the exact requested action and the user approves it.
"""
from __future__ import annotations

import asyncio
import os
import platform
import shutil
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


class CreateTextFileTool(Tool):
    """Create one new UTF-8 text file without overwriting existing data."""

    _MAX_TEXT_LENGTH = 100_000

    def __init__(self) -> None:
        self.name = "filesystem.create_text_file"
        self.description = (
            "Create a new UTF-8 text file at an exact local path after the user confirms. "
            "Never overwrites an existing file or creates directories."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "New file path."},
                "text": {"type": "string", "description": "Text to put in the new file."},
            },
            "required": ["path", "text"],
            "additionalProperties": False,
        }
        self.permission = PermissionLevel.CONFIRM

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        path = arguments.get("path")
        text = arguments.get("text")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("'path' must be a non-empty string")
        if not isinstance(text, str):
            raise TypeError("'text' must be a string")
        if len(text) > self._MAX_TEXT_LENGTH:
            raise ValueError(f"'text' must be {self._MAX_TEXT_LENGTH} characters or fewer")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path = Path(arguments["path"]).expanduser()
        if path.is_symlink() or path.parent.is_symlink():
            return ToolResult(False, "", error="Refusing to create a file through a symlink.")
        if path.exists():
            return ToolResult(False, "", error=f"Path already exists: {path}")
        if not path.parent.is_dir():
            return ToolResult(False, "", error=f"Parent directory does not exist: {path.parent}")
        try:
            resolved = await asyncio.to_thread(_create_new_text_file, path, arguments["text"])
        except FileExistsError:
            return ToolResult(False, "", error=f"Path already exists: {path}")
        except OSError:
            return ToolResult(False, "", error="Could not create the text file safely.")
        return ToolResult(
            True,
            "Created the text file.",
            data={"path": str(resolved), "characters": len(arguments["text"])},
        )


class MoveFileTool(Tool):
    """Move one regular file without allowing destination replacement."""

    def __init__(self) -> None:
        self.name = "filesystem.move_file"
        self.description = (
            "Move one existing regular file to a new local path after the user confirms. "
            "Never replaces an existing destination or moves directories or symlinks."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Existing file to move."},
                "destination": {"type": "string", "description": "New file path."},
            },
            "required": ["source", "destination"],
            "additionalProperties": False,
        }
        self.permission = PermissionLevel.CONFIRM

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        for name in ("source", "destination"):
            value = arguments.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"'{name}' must be a non-empty string")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        source = Path(arguments["source"]).expanduser()
        destination = Path(arguments["destination"]).expanduser()
        if source.is_symlink() or destination.is_symlink() or destination.parent.is_symlink():
            return ToolResult(False, "", error="Refusing to move a file through a symlink.")
        if not source.is_file():
            return ToolResult(False, "", error=f"Source is not a regular file: {source}")
        if destination.exists():
            return ToolResult(False, "", error=f"Destination already exists: {destination}")
        if not destination.parent.is_dir():
            return ToolResult(False, "", error=f"Destination directory does not exist: {destination.parent}")
        try:
            resolved_source, resolved_destination = await asyncio.to_thread(
                _move_file_without_replacing, source, destination
            )
        except FileExistsError:
            return ToolResult(False, "", error=f"Destination already exists: {destination}")
        except OSError:
            return ToolResult(False, "", error="Could not move the file safely.")
        return ToolResult(
            True,
            "Moved the file.",
            data={"source": str(resolved_source), "destination": str(resolved_destination)},
        )


async def _run_open(command: list[str], failure: str, data: dict[str, str]) -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
    )
    await asyncio.wait_for(process.communicate(), timeout=10)
    if process.returncode != 0:
        return ToolResult(False, "", error=failure)
    return ToolResult(True, "Opened successfully.", data=data)


def _create_new_text_file(path: Path, text: str) -> Path:
    """Create exclusively, so a race cannot overwrite another file."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(text)
        file.flush()
        os.fsync(file.fileno())
    return path.resolve()


def _move_file_without_replacing(source: Path, destination: Path) -> tuple[Path, Path]:
    """Copy using exclusive creation, then remove the source only after success."""
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with source.open("rb") as input_file, os.fdopen(descriptor, "wb") as output_file:
            shutil.copyfileobj(input_file, output_file)
            output_file.flush()
            os.fsync(output_file.fileno())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    source.unlink()
    return source.resolve(), destination.resolve()
