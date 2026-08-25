from typing import Any, ClassVar

import pytest

from atlas.core.tools.base import PermissionLevel, Tool, ToolResult
from atlas.core.tools.registry import PermissionDeniedError, ToolNotFoundError, ToolRegistry


class _EchoTool(Tool):
    name = "echo"
    description = "Echoes back the given text."
    parameters: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }
    permission = PermissionLevel.READ_ONLY

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        if "text" not in arguments:
            raise ValueError("'text' is required")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, content=arguments["text"])


class _DeleteTool(_EchoTool):
    name = "delete_everything"
    permission = PermissionLevel.PRIVILEGED


async def test_read_only_tool_runs_without_confirmation() -> None:
    registry = ToolRegistry()
    registry.register(_EchoTool())
    result = await registry.dispatch("echo", {"text": "hi"})
    assert result.success
    assert result.content == "hi"


async def test_unknown_tool_raises() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        await registry.dispatch("nope", {})


async def test_privileged_tool_without_confirmation_handler_is_denied() -> None:
    registry = ToolRegistry()
    registry.register(_DeleteTool())
    with pytest.raises(PermissionDeniedError):
        await registry.dispatch("delete_everything", {"text": "x"})


async def test_privileged_tool_respects_declined_confirmation() -> None:
    async def deny(name: str, args: dict[str, Any]) -> bool:
        return False

    registry = ToolRegistry(confirm=deny)
    registry.register(_DeleteTool())
    result = await registry.dispatch("delete_everything", {"text": "x"})
    assert result.success is False
    assert result.error == "User declined confirmation"
