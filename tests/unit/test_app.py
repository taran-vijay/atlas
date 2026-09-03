from atlas.app import AtlasDesktopApp, ConnectionScreen, _create_assistant


def test_desktop_module_exposes_assistant_factory() -> None:
    assert callable(_create_assistant)


def test_desktop_module_exposes_connection_verified_boot_screen() -> None:
    assert ConnectionScreen.__doc__ is not None


def test_desktop_app_exposes_live_atlas_field_updates() -> None:
    assert hasattr(AtlasDesktopApp, "_refresh_field")
    assert hasattr(AtlasDesktopApp, "_set_field_state")
