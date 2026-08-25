from pathlib import Path
from unittest.mock import patch

import pytest

from atlas.core.tools.system_tools import (
    GetBatteryTool,
    GetNetworkInfoTool,
    GetProcessesTool,
    GetSystemInfoTool,
    GetTimeTool,
    ListDirectoryTool,
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


@pytest.mark.asyncio
async def test_get_battery_parses_macos_output() -> None:
    output = "Now drawing from 'AC Power'\n -InternalBattery-0 (id=123)\t95%; charging; 0:00 remaining present: true\n"
    with patch("atlas.core.tools.system_tools.platform.system", return_value="Darwin"):
        with patch("atlas.core.tools.system_tools.subprocess.run") as run:
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
    with patch("atlas.core.tools.system_tools.platform.system", return_value="Darwin"):
        with patch("atlas.core.tools.system_tools.subprocess.run") as run:
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
    with patch("atlas.core.tools.system_tools.socket.gethostname", return_value="atlas-test"):
        with patch(
            "atlas.core.tools.system_tools.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("192.168.1.20", 0))],
        ):
            with patch("atlas.core.tools.system_tools.socket.if_nameindex", return_value=[(1, "en0")]):
                result = await GetNetworkInfoTool().execute({})

    assert result.success
    assert result.data == {
        "hostname": "atlas-test",
        "addresses": ["192.168.1.20"],
        "interfaces": ["en0"],
    }
