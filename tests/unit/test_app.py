from atlas.app import ConnectionScreen, _create_assistant


def test_desktop_module_exposes_assistant_factory() -> None:
    assert callable(_create_assistant)


def test_desktop_module_exposes_connection_verified_boot_screen() -> None:
    assert ConnectionScreen.__doc__ is not None
