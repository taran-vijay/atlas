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
