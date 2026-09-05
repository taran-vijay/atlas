from atlas.app import _DEVICE_ASSET, AtlasDesktopApp, ConnectionScreen, _create_assistant


def test_desktop_module_exposes_assistant_factory() -> None:
    assert callable(_create_assistant)


def test_desktop_module_exposes_connection_verified_boot_screen() -> None:
    assert ConnectionScreen.__doc__ is not None


def test_desktop_app_exposes_live_atlas_field_updates() -> None:
    assert hasattr(AtlasDesktopApp, "_refresh_field")
    assert hasattr(AtlasDesktopApp, "_set_field_state")
    assert hasattr(AtlasDesktopApp, "_animate_top_dot")


def test_desktop_app_includes_device_status_visual() -> None:
    assert _DEVICE_ASSET.is_file()
