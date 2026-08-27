from atlas.cli import _build_tool_registry


def test_cli_registers_v02_tools() -> None:
    registry = _build_tool_registry()

    assert [schema["function"]["name"] for schema in registry.list_schemas()] == [
        "system.get_time",
        "system.get_system_info",
        "filesystem.list_directory",
        "filesystem.read_file",
        "filesystem.get_metadata",
        "filesystem.search",
        "system.get_battery",
        "system.get_processes",
        "system.get_network_info",
    ]
