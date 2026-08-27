from typing import Any

from atlas.core.tools.base import PermissionLevel, Tool, ToolResult
from atlas.core.tools.registry import ToolRegistry


class _EchoTool(Tool):
    def __init__(self) -> None:
        self.name = "echo"
        self.description = "Echoes back the given text."
        self.parameters: dict[str, Any] = {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        }
        self.permission = PermissionLevel.READ_ONLY

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        if "text" not in arguments:
            raise ValueError("'text' is required")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(success=True, content=arguments["text"])


class _DeleteTool(_EchoTool):
    def __init__(self) -> None:
        super().__init__()
        self.name = "delete_everything"
        self.permission = PermissionLevel.PRIVILEGED


async def test_read_only_tool_runs_without_confirmation() -> None:
    registry = ToolRegistry()
    registry.register(_EchoTool())
    result = await registry.dispatch("echo", {"text": "hi"})
    assert result.success
    assert result.content == "hi"


async def test_invalid_arguments_return_tool_error_without_raising() -> None:
    registry = ToolRegistry()
    registry.register(_EchoTool())
    result = await registry.dispatch("echo", {})
    assert result.success is False
    assert result.error == "Invalid arguments for 'echo': 'text' is required"


async def test_unknown_tool_returns_structured_error() -> None:
    registry = ToolRegistry()
    result = await registry.dispatch("nope", {})
    assert result.success is False
    assert result.error == "Unknown tool: 'nope'."


async def test_privileged_tool_without_confirmation_handler_returns_error() -> None:
    registry = ToolRegistry()
    registry.register(_DeleteTool())
    result = await registry.dispatch("delete_everything", {"text": "x"})
    assert result.success is False
    assert "requires confirmation" in (result.error or "")


async def test_privileged_tool_respects_declined_confirmation() -> None:
    async def deny(name: str, args: dict[str, Any]) -> bool:
        return False

    registry = ToolRegistry(confirm=deny)
    registry.register(_DeleteTool())
    result = await registry.dispatch("delete_everything", {"text": "x"})
    assert result.success is False
    assert result.error == "User declined confirmation"
