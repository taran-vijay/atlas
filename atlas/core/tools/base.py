"""Tool contract and permission model.

The LLM never executes anything on the system directly. It emits a
structured tool call; ToolRegistry validates the arguments and checks
permissions before a Tool's execute() ever runs. See docs/security-model.md.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


class PermissionLevel(str, Enum):
    READ_ONLY = "read_only"    # runs immediately, no confirmation
    CONFIRM = "confirm"        # requires explicit user confirmation
    PRIVILEGED = "privileged"  # requires confirmation + extra audit detail


@dataclass
class ToolResult:
    success: bool
    content: str
    data: dict[str, Any] | None = None
    error: str | None = None

    def to_llm_content(self, tool_name: str) -> str:
        """Serialize an outcome in a stable, machine-readable form for the LLM.

        Tool output can contain arbitrary local data, so it is deliberately kept
        as data rather than being spliced into an instruction-like prompt.
        """
        payload: dict[str, Any] = {"tool": tool_name, "status": "success"}
        if self.success:
            payload["data"] = self.data
            payload["display"] = self.content
        else:
            payload["status"] = "error"
            payload["error"] = self.error or "The tool failed without an error message."
        return json.dumps(payload, sort_keys=True, default=str)


class Tool(ABC):
    """Base class every tool implementation must extend."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for arguments
    permission: PermissionLevel

    @abstractmethod
    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        """Raise ValueError if arguments don't satisfy the tool's schema/invariants."""

    @abstractmethod
    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """Perform the tool's action. Only called after validation and permission checks."""

    def to_llm_schema(self) -> dict[str, Any]:
        """Describe this tool the way the LLM backend expects to see it."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
