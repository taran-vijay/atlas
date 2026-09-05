from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from atlas.core.tools.action_tools import CopyToClipboardTool, OpenApplicationTool, OpenFileTool
from atlas.core.tools.registry import ToolRegistry


class _Process:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.communicate = AsyncMock(return_value=(b"", b""))


def test_open_application_validates_name() -> None:
    with pytest.raises(ValueError):
        OpenApplicationTool().validate_arguments({"app": ""})


async def test_open_application_runs_only_after_approval() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def approve(name: str, arguments: dict[str, object]) -> bool:
        calls.append((name, arguments))
        return True

    process = _Process()
    registry = ToolRegistry(confirm=approve)
    registry.register(OpenApplicationTool())
    with (
        patch("atlas.core.tools.action_tools.platform.system", return_value="Darwin"),
        patch("atlas.core.tools.action_tools.asyncio.create_subprocess_exec", return_value=process) as spawn,
    ):
        result = await registry.dispatch("desktop.open_application", {"app": "Calculator"})

    assert result.success is True
    assert calls == [("desktop.open_application", {"app": "Calculator"})]
    spawn.assert_awaited_once()


async def test_open_application_never_runs_when_declined() -> None:
    async def decline(name: str, arguments: dict[str, object]) -> bool:
        return False

    registry = ToolRegistry(confirm=decline)
    registry.register(OpenApplicationTool())
    with patch("atlas.core.tools.action_tools.asyncio.create_subprocess_exec") as spawn:
        result = await registry.dispatch("desktop.open_application", {"app": "Calculator"})

    assert result.success is False
    assert result.error == "User declined confirmation"
    spawn.assert_not_called()


async def test_open_file_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "private.txt"
    target.write_text("private", encoding="utf-8")
    link = tmp_path / "alias.txt"
    link.symlink_to(target)

    with patch("atlas.core.tools.action_tools.platform.system", return_value="Darwin"):
        result = await OpenFileTool().execute({"path": str(link)})

    assert result.success is False
    assert result.error == "Refusing to open a symlink."


async def test_copy_to_clipboard_reports_character_count() -> None:
    process = _Process()
    with (
        patch("atlas.core.tools.action_tools.platform.system", return_value="Darwin"),
        patch("atlas.core.tools.action_tools.asyncio.create_subprocess_exec", return_value=process),
    ):
        result = await CopyToClipboardTool().execute({"text": "Hello"})

    assert result.success is True
    assert result.data == {"characters": 5}
    process.communicate.assert_awaited_once_with(b"Hello")
