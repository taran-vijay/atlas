from unittest.mock import patch

from atlas.cli import _build_tool_registry, main


def test_cli_registers_read_and_confirmation_gated_tools() -> None:
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
        "desktop.open_application",
        "desktop.open_file",
        "desktop.copy_to_clipboard",
        "filesystem.create_text_file",
        "filesystem.create_folder",
        "filesystem.copy_file",
        "filesystem.move_file",
        "filesystem.rename_file",
        "filesystem.move_to_trash",
    ]


def test_local_command_starts_the_desktop_app() -> None:
    with (
        patch("atlas.cli.sys.argv", ["atlas", "local"]),
        patch("atlas.app.main") as desktop_main,
    ):
        main()

    desktop_main.assert_called_once_with()
