from pathlib import Path

import pytest

from atlas.core.tools.system_tools import GetSystemInfoTool, GetTimeTool, ListDirectoryTool


@pytest.mark.asyncio
async def test_get_time_returns_local_time_data():
    result = await GetTimeTool().execute({})

    assert result.success
    assert result.content
    assert result.data is not None
    assert "iso" in result.data
    assert "timezone" in result.data


@pytest.mark.asyncio
async def test_get_time_rejects_arguments():
    with pytest.raises(ValueError):
        GetTimeTool().validate_arguments({"unexpected": True})


@pytest.mark.asyncio
async def test_get_system_info_returns_expected_fields():
    result = await GetSystemInfoTool().execute({})

    assert result.success
    assert result.data is not None
    assert {"operating_system", "os_version", "machine", "processor", "python_version"} <= set(result.data)


@pytest.mark.asyncio
async def test_list_directory_returns_entries(tmp_path: Path):
    (tmp_path / "file.txt").write_text("hello", encoding="utf-8")
    (tmp_path / "folder").mkdir()

    result = await ListDirectoryTool().execute({"path": str(tmp_path)})

    assert result.success
    assert result.data is not None
    assert [entry["name"] for entry in result.data["entries"]] == ["folder", "file.txt"]


@pytest.mark.asyncio
async def test_list_directory_rejects_missing_path():
    result = await ListDirectoryTool().execute({"path": "/definitely/not/a/real/path"})

    assert result.success is False
    assert "does not exist" in (result.error or "")


def test_list_directory_requires_path():
    with pytest.raises(ValueError):
        ListDirectoryTool().validate_arguments({})
