from pathlib import Path
from unittest.mock import patch

import pytest

from atlas.core.tools.system_tools import (
    GetBatteryTool,
    GetFileMetadataTool,
    GetNetworkInfoTool,
    GetProcessesTool,
    GetSystemInfoTool,
    GetTimeTool,
    ListDirectoryTool,
    ReadFileTool,
    SearchFilesTool,
)


@pytest.mark.asyncio
async def test_get_time_returns_local_time_data() -> None:
    result = await GetTimeTool().execute({})

    assert result.success
    assert result.content
    assert result.data is not None
    assert "iso" in result.data
    assert "timezone" in result.data


@pytest.mark.asyncio
async def test_get_time_rejects_arguments() -> None:
    with pytest.raises(ValueError):
        GetTimeTool().validate_arguments({"unexpected": True})


@pytest.mark.asyncio
async def test_get_system_info_returns_expected_fields() -> None:
    result = await GetSystemInfoTool().execute({})

    assert result.success
    assert result.data is not None
    assert {"operating_system", "os_version", "machine", "processor", "python_version"} <= set(result.data)


@pytest.mark.asyncio
async def test_list_directory_returns_entries(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "folder").mkdir()

    result = await ListDirectoryTool().execute({"path": str(tmp_path)})

    assert result.success
    assert result.data is not None
    assert [entry["name"] for entry in result.data["entries"]] == ["folder", "file.txt"]


@pytest.mark.asyncio
async def test_list_directory_rejects_missing_path() -> None:
    result = await ListDirectoryTool().execute({"path": "/definitely/not/a/real/path"})

    assert result.success is False
    assert "does not exist" in (result.error or "")


def test_list_directory_requires_path() -> None:
    with pytest.raises(ValueError):
        ListDirectoryTool().validate_arguments({})


async def test_read_file_returns_bounded_text(tmp_path: Path) -> None:
    file = tmp_path / "notes.txt"
    file.write_text("Atlas notes", encoding="utf-8")

    result = await ReadFileTool().execute({"path": str(file)})

    assert result.success is True
    assert result.data is not None
    assert result.data["content"] == "Atlas notes"
    assert result.data["truncated"] is False


async def test_read_file_rejects_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("private", encoding="utf-8")
    link = tmp_path / "linked.txt"
    link.symlink_to(target)

    result = await ReadFileTool().execute({"path": str(link)})

    assert result.success is False
    assert result.error == "Refusing to read a symlink."


async def test_get_file_metadata_reports_file_type(tmp_path: Path) -> None:
    file = tmp_path / "report.txt"
    file.write_text("hello", encoding="utf-8")

    result = await GetFileMetadataTool().execute({"path": str(file)})

    assert result.success is True
    assert result.data is not None
    assert result.data["type"] == "file"
    assert result.data["size_bytes"] == 5


async def test_search_files_returns_bounded_name_matches(tmp_path: Path) -> None:
    (tmp_path / "atlas-notes.txt").write_text("one", encoding="utf-8")
    (tmp_path / "Atlas-plan.md").write_text("two", encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("three", encoding="utf-8")

    result = await SearchFilesTool().execute({"path": str(tmp_path), "query": "atlas", "limit": 1})

    assert result.success is True
    assert result.data is not None
    assert len(result.data["matches"]) == 1
    assert "atlas" in result.data["matches"][0].casefold()


def test_search_files_rejects_invalid_limit() -> None:
    with pytest.raises(ValueError):
        SearchFilesTool().validate_arguments({"path": "/tmp", "query": "atlas", "limit": 0})


@pytest.mark.asyncio
async def test_get_battery_parses_macos_output() -> None:
    output = "Now drawing from 'AC Power'\n -InternalBattery-0 (id=123)\t95%; charging; 0:00 remaining present: true\n"
    with (
        patch("atlas.core.tools.system_tools.platform.system", return_value="Darwin"),
        patch("atlas.core.tools.system_tools.subprocess.run") as run,
    ):
        run.return_value.returncode = 0
        run.return_value.stdout = output
        result = await GetBatteryTool().execute({})

    assert result.success
    assert result.data == {"percentage": 95, "charging": True}


@pytest.mark.asyncio
async def test_get_battery_reports_unsupported_os() -> None:
    with patch("atlas.core.tools.system_tools.platform.system", return_value="Linux"):
        result = await GetBatteryTool().execute({})

    assert result.success is False
    assert "not implemented" in (result.error or "")


@pytest.mark.asyncio
async def test_get_processes_parses_unix_output() -> None:
    output = " 101  12.5  3.2 /usr/bin/first\n 202   2.0  1.1 /usr/bin/second\n"
    with (
        patch("atlas.core.tools.system_tools.platform.system", return_value="Darwin"),
        patch("atlas.core.tools.system_tools.subprocess.run") as run,
    ):
        run.return_value.returncode = 0
        run.return_value.stdout = output
        result = await GetProcessesTool().execute({"limit": 1})

    assert result.success
    assert result.data is not None
    processes = result.data["processes"]
    assert len(processes) == 1
    assert processes[0]["pid"] == 101


def test_get_processes_rejects_invalid_limit() -> None:
    with pytest.raises(ValueError):
        GetProcessesTool().validate_arguments({"limit": 0})


@pytest.mark.asyncio
async def test_get_network_info_returns_local_identity() -> None:
    with (
        patch("atlas.core.tools.system_tools.socket.gethostname", return_value="atlas-test"),
        patch(
            "atlas.core.tools.system_tools.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("192.168.1.20", 0))],
        ),
        patch("atlas.core.tools.system_tools.socket.if_nameindex", return_value=[(1, "en0")]),
    ):
        result = await GetNetworkInfoTool().execute({})

    assert result.success
    assert result.data == {
        "hostname": "atlas-test",
        "addresses": ["192.168.1.20"],
        "interfaces": ["en0"],
    }
