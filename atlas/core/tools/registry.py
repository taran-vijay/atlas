"""Registry that owns every tool and enforces the permission gate.

This is the single choke point between an LLM's tool call and anything that
touches the local OS, network, or user data. No component should call
Tool.execute() directly -- everything routes through ToolRegistry.dispatch().
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from atlas.core.tools.base import PermissionLevel, Tool, ToolResult

ConfirmationCallback = Callable[[str, dict[str, Any]], Awaitable[bool]]


class ToolNotFoundError(Exception):
    pass


class PermissionDeniedError(Exception):
    pass


class ToolRegistry:
    def __init__(self, *, confirm: ConfirmationCallback | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self._confirm = confirm

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(name) from exc

    def list_schemas(self) -> list[dict[str, Any]]:
        return [tool.to_llm_schema() for tool in self._tools.values()]

    async def dispatch(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tool = self.get(name)
        tool.validate_arguments(arguments)

        if tool.permission in (PermissionLevel.CONFIRM, PermissionLevel.PRIVILEGED):
            if self._confirm is None:
                raise PermissionDeniedError(
                    f"'{tool.name}' requires confirmation but no confirmation "
                    "handler is configured"
                )
            approved = await self._confirm(tool.name, arguments)
            if not approved:
                return ToolResult(success=False, content="", error="User declined confirmation")

        return await tool.execute(arguments)
