from atlas.cli import _build_tool_registry


def test_cli_registers_v01_tools() -> None:
    registry = _build_tool_registry()

    assert [schema["function"]["name"] for schema in registry.list_schemas()] == [
        "system.get_time",
        "system.get_system_info",
        "filesystem.list_directory",
    ]
