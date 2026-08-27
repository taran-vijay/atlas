"""Safe, read-only tools for interacting with the local system."""
from __future__ import annotations

import asyncio
import platform
import re
import socket
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from atlas.core.tools.base import PermissionLevel, Tool, ToolResult


class GetTimeTool(Tool):
    def __init__(self) -> None:
        self.name = "system.get_time"
        self.description = "Return the current local date and time of the machine running Atlas."
        self.parameters = {"type": "object", "properties": {}, "additionalProperties": False}
        self.permission = PermissionLevel.READ_ONLY

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        if arguments:
            raise ValueError("system.get_time does not accept arguments")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        now = datetime.now().astimezone()
        return ToolResult(success=True, content=now.strftime("%A, %B %d, %Y at %I:%M:%S %p %Z"), data={"iso": now.isoformat(), "timezone": str(now.tzinfo)})


class GetSystemInfoTool(Tool):
    def __init__(self) -> None:
        self.name = "system.get_system_info"
        self.description = "Return basic operating system and hardware information for the machine running Atlas."
        self.parameters = {"type": "object", "properties": {}, "additionalProperties": False}
        self.permission = PermissionLevel.READ_ONLY

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        if arguments:
            raise ValueError("system.get_system_info does not accept arguments")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        info = {"operating_system": platform.system(), "os_version": platform.version(), "machine": platform.machine(), "processor": platform.processor() or "unknown", "python_version": platform.python_version()}
        content = f"OS: {info['operating_system']} {info['os_version']}; architecture: {info['machine']}; processor: {info['processor']}; Python: {info['python_version']}"
        return ToolResult(success=True, content=content, data=info)


class ListDirectoryTool(Tool):
    def __init__(self) -> None:
        self.name = "filesystem.list_directory"
        self.description = "List the immediate contents of a local directory. This is read-only and does not modify files."
        self.parameters = {"type": "object", "properties": {"path": {"type": "string", "description": "Absolute or user-home-relative directory path to list."}}, "required": ["path"], "additionalProperties": False}
        self.permission = PermissionLevel.READ_ONLY

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
        data = {"path": str(path), "entries": [{"name": e.name, "type": "directory" if e.is_dir() else "file"} for e in entries]}
        lines = [f"{'[DIR]' if e.is_dir() else '[FILE]'} {e.name}" for e in entries]
        content = f"Contents of {path}:\n" + "\n".join(lines) if lines else f"Directory {path} is empty."
        return ToolResult(success=True, content=content, data=data)


class ReadFileTool(Tool):
    """Read a bounded UTF-8 text file without following symlinks."""

    _DEFAULT_MAX_BYTES = 65_536
    _MAX_BYTES = 262_144

    def __init__(self) -> None:
        self.name = "filesystem.read_file"
        self.description = (
            "Read a bounded UTF-8 text file. This is read-only; binary files, directories, "
            "and symlinks are rejected."
        )
        self.parameters = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path of the text file to read."},
                "max_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": self._MAX_BYTES,
                    "default": self._DEFAULT_MAX_BYTES,
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        }
        self.permission = PermissionLevel.READ_ONLY

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("'path' must be a non-empty string")
        max_bytes = arguments.get("max_bytes", self._DEFAULT_MAX_BYTES)
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool):
            raise TypeError("'max_bytes' must be an integer")
        if not 1 <= max_bytes <= self._MAX_BYTES:
            raise ValueError(f"'max_bytes' must be between 1 and {self._MAX_BYTES}")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path = Path(arguments["path"]).expanduser()
        max_bytes = arguments.get("max_bytes", self._DEFAULT_MAX_BYTES)
        if path.is_symlink():
            return ToolResult(success=False, content="", error="Refusing to read a symlink.")
        if not path.exists():
            return ToolResult(success=False, content="", error=f"Path does not exist: {path}")
        if not path.is_file():
            return ToolResult(success=False, content="", error=f"Path is not a regular file: {path}")

        try:
            contents = await asyncio.to_thread(self._read_text, path, max_bytes)
        except UnicodeDecodeError:
            return ToolResult(success=False, content="", error="File is not valid UTF-8 text.")
        except OSError:
            return ToolResult(success=False, content="", error=f"Could not read file: {path}")

        truncated = path.stat().st_size > len(contents.encode("utf-8"))
        data = {"path": str(path.resolve()), "content": contents, "truncated": truncated}
        suffix = "\n[Output truncated.]" if truncated else ""
        return ToolResult(success=True, content=contents + suffix, data=data)

    @staticmethod
    def _read_text(path: Path, max_bytes: int) -> str:
        with path.open("rb") as file:
            return file.read(max_bytes).decode("utf-8")


class GetFileMetadataTool(Tool):
    def __init__(self) -> None:
        self.name = "filesystem.get_metadata"
        self.description = "Return read-only metadata for a local file or directory."
        self.parameters = {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Path to inspect."}},
            "required": ["path"],
            "additionalProperties": False,
        }
        self.permission = PermissionLevel.READ_ONLY

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        path = arguments.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("'path' must be a non-empty string")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path = Path(arguments["path"]).expanduser()
        if not path.exists() and not path.is_symlink():
            return ToolResult(success=False, content="", error=f"Path does not exist: {path}")
        try:
            stat = await asyncio.to_thread(path.lstat)
        except OSError:
            return ToolResult(success=False, content="", error=f"Could not inspect path: {path}")

        if path.is_symlink():
            kind = "symlink"
        elif path.is_dir():
            kind = "directory"
        elif path.is_file():
            kind = "file"
        else:
            kind = "other"
        data = {
            "path": str(path.absolute()),
            "type": kind,
            "size_bytes": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
        }
        content = (
            f"{kind.title()}: {data['path']}\nSize: {stat.st_size} bytes\n"
            f"Modified: {data['modified_at']}"
        )
        return ToolResult(success=True, content=content, data=data)


class SearchFilesTool(Tool):
    _DEFAULT_LIMIT = 20
    _MAX_LIMIT = 100

    def __init__(self) -> None:
        self.name = "filesystem.search"
        self.description = "Search file and directory names beneath a local directory without reading contents."
        self.parameters = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory to search."},
                "query": {"type": "string", "description": "Case-insensitive filename text to find."},
                "limit": {"type": "integer", "minimum": 1, "maximum": self._MAX_LIMIT, "default": self._DEFAULT_LIMIT},
            },
            "required": ["path", "query"],
            "additionalProperties": False,
        }
        self.permission = PermissionLevel.READ_ONLY

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        for key in ("path", "query"):
            value = arguments.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"'{key}' must be a non-empty string")
        limit = arguments.get("limit", self._DEFAULT_LIMIT)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise TypeError("'limit' must be an integer")
        if not 1 <= limit <= self._MAX_LIMIT:
            raise ValueError(f"'limit' must be between 1 and {self._MAX_LIMIT}")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        root = Path(arguments["path"]).expanduser()
        if not root.exists():
            return ToolResult(success=False, content="", error=f"Path does not exist: {root}")
        if not root.is_dir():
            return ToolResult(success=False, content="", error=f"Path is not a directory: {root}")
        limit = arguments.get("limit", self._DEFAULT_LIMIT)
        try:
            matches = await asyncio.to_thread(
                self._find_matches, root, arguments["query"].casefold(), limit
            )
        except OSError:
            return ToolResult(success=False, content="", error=f"Could not search directory: {root}")

        data = {"path": str(root.resolve()), "query": arguments["query"], "matches": matches}
        content = "\n".join(matches) if matches else "No matching paths found."
        return ToolResult(success=True, content=content, data=data)

    @staticmethod
    def _find_matches(root: Path, query: str, limit: int) -> list[str]:
        matches: list[str] = []
        for path in root.rglob("*"):
            if query in path.name.casefold():
                matches.append(str(path))
                if len(matches) == limit:
                    break
        return matches


class GetBatteryTool(Tool):
    def __init__(self) -> None:
        self.name = "system.get_battery"
        self.description = "Return the current battery level and charging state when supported by the operating system."
        self.parameters = {"type": "object", "properties": {}, "additionalProperties": False}
        self.permission = PermissionLevel.READ_ONLY

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        if arguments:
            raise ValueError("system.get_battery does not accept arguments")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        if platform.system() != "Darwin":
            return ToolResult(success=False, content="", error="Battery telemetry is not implemented for this OS yet.")
        completed = await asyncio.to_thread(subprocess.run, ["pmset", "-g", "batt"], capture_output=True, text=True, check=False, timeout=5)
        if completed.returncode != 0:
            return ToolResult(success=False, content="", error="Battery telemetry command failed.")
        match = re.search(r"(\d+)%", completed.stdout)
        if not match:
            return ToolResult(success=False, content="", error="Battery percentage was not reported.")
        percentage = int(match.group(1))
        charging = "charging" in completed.stdout.lower() and "discharging" not in completed.stdout.lower()
        data = {"percentage": percentage, "charging": charging}
        state = "charging" if charging else "not charging"
        return ToolResult(success=True, content=f"Battery: {percentage}% ({state}).", data=data)


class GetProcessesTool(Tool):
    def __init__(self) -> None:
        self.name = "system.get_processes"
        self.description = "Return a read-only snapshot of currently running processes and resource usage."
        self.parameters = {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}}, "additionalProperties": False}
        self.permission = PermissionLevel.READ_ONLY

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        limit = arguments.get("limit", 10)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("'limit' must be an integer between 1 and 50")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        limit = arguments.get("limit", 10)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise TypeError("'limit' must be an integer")
        if not 1 <= limit <= 50:
            raise ValueError("'limit' must be an integer between 1 and 50")
        command = ["ps", "-axo", "pid=,pcpu=,pmem=,comm="] if platform.system() != "Windows" else ["tasklist"]
        completed = await asyncio.to_thread(subprocess.run, command, capture_output=True, text=True, check=False, timeout=5)
        if completed.returncode != 0:
            return ToolResult(success=False, content="", error="Process listing failed.")
        processes: list[dict[str, Any]] = []
        for line in completed.stdout.splitlines():
            parts = line.split(None, 3)
            if len(parts) == 4:
                try:
                    processes.append({"pid": int(parts[0]), "cpu_percent": float(parts[1]), "memory_percent": float(parts[2]), "command": parts[3]})
                except ValueError:
                    continue
        processes.sort(key=lambda item: float(item["cpu_percent"]), reverse=True)
        processes = processes[:limit]
        content = "Top processes by CPU:\n" + "\n".join(f"PID {p['pid']}: {p['cpu_percent']:.1f}% CPU, {p['memory_percent']:.1f}% memory, {p['command']}" for p in processes) if processes else "No processes were reported."
        return ToolResult(success=True, content=content, data={"processes": processes})


class GetNetworkInfoTool(Tool):
    def __init__(self) -> None:
        self.name = "system.get_network_info"
        self.description = "Return basic local network identity and interface information without modifying network configuration."
        self.parameters = {"type": "object", "properties": {}, "additionalProperties": False}
        self.permission = PermissionLevel.READ_ONLY

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        if arguments:
            raise ValueError("system.get_network_info does not accept arguments")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        hostname = socket.gethostname()
        addresses = sorted({str(address[4][0]) for address in socket.getaddrinfo(hostname, None) if address[4]})
        interfaces = [name for _, name in socket.if_nameindex()]
        data = {"hostname": hostname, "addresses": addresses, "interfaces": interfaces}
        content = f"Hostname: {hostname}\nAddresses: {', '.join(addresses) or 'none'}\nInterfaces: {', '.join(interfaces) or 'none'}"
        return ToolResult(success=True, content=content, data=data)
