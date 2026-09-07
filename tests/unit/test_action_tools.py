from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from atlas.core.tools.action_tools import (
    CopyToClipboardTool,
    CreateTextFileTool,
    MoveFileTool,
    OpenApplicationTool,
    OpenFileTool,
)
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


async def test_create_text_file_writes_new_utf8_file(tmp_path: Path) -> None:
    path = tmp_path / "atlas-note.txt"

    result = await CreateTextFileTool().execute({"path": str(path), "text": "Mission log"})

    assert result.success is True
    assert path.read_text(encoding="utf-8") == "Mission log"
    assert result.data == {"path": str(path.resolve()), "characters": 11}


async def test_create_text_file_never_runs_when_confirmation_is_declined(tmp_path: Path) -> None:
    async def decline(name: str, arguments: dict[str, object]) -> bool:
        return False

    path = tmp_path / "atlas-note.txt"
    registry = ToolRegistry(confirm=decline)
    registry.register(CreateTextFileTool())

    result = await registry.dispatch(
        "filesystem.create_text_file", {"path": str(path), "text": "Mission log"}
    )

    assert result.success is False
    assert result.error == "User declined confirmation"
    assert path.exists() is False


async def test_create_text_file_does_not_overwrite_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "atlas-note.txt"
    path.write_text("original", encoding="utf-8")

    result = await CreateTextFileTool().execute({"path": str(path), "text": "replacement"})

    assert result.success is False
    assert "already exists" in (result.error or "")
    assert path.read_text(encoding="utf-8") == "original"


async def test_move_file_moves_to_new_path_without_replacing(tmp_path: Path) -> None:
    source = tmp_path / "inbox" / "report.txt"
    source.parent.mkdir()
    source.write_text("Atlas report", encoding="utf-8")
    destination = tmp_path / "archive" / "report.txt"
    destination.parent.mkdir()

    result = await MoveFileTool().execute(
        {"source": str(source), "destination": str(destination)}
    )

    assert result.success is True
    assert source.exists() is False
    assert destination.read_text(encoding="utf-8") == "Atlas report"


async def test_move_file_never_replaces_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    destination = tmp_path / "destination.txt"
    source.write_text("source", encoding="utf-8")
    destination.write_text("original destination", encoding="utf-8")

    result = await MoveFileTool().execute(
        {"source": str(source), "destination": str(destination)}
    )

    assert result.success is False
    assert "already exists" in (result.error or "")
    assert source.read_text(encoding="utf-8") == "source"
    assert destination.read_text(encoding="utf-8") == "original destination"
