from unittest.mock import AsyncMock

from atlas.app import (
    _DEVICE_ASSET,
    _STARTUP_ANNOUNCEMENT,
    AtlasDesktopApp,
    ConnectionScreen,
    _create_assistant,
    _speak_startup_sequence,
)
from atlas.core.memory.base import VoiceSettings


def test_desktop_module_exposes_assistant_factory() -> None:
    assert callable(_create_assistant)


def test_desktop_module_exposes_connection_verified_boot_screen() -> None:
    assert ConnectionScreen.__doc__ is not None


def test_desktop_app_exposes_live_atlas_field_updates() -> None:
    assert hasattr(AtlasDesktopApp, "_refresh_field")
    assert hasattr(AtlasDesktopApp, "_set_field_state")
    assert hasattr(AtlasDesktopApp, "_animate_core")
    assert hasattr(AtlasDesktopApp, "_reflow_for_width")
    assert hasattr(AtlasDesktopApp, "_update_input_status")


def test_desktop_app_uses_explicit_hold_to_talk_without_a_wake_listener() -> None:
    assert hasattr(AtlasDesktopApp, "_start_recording")
    assert hasattr(AtlasDesktopApp, "_stop_recording")
    assert not hasattr(AtlasDesktopApp, "_activate_wake_listener")
    assert not hasattr(AtlasDesktopApp, "_toggle_recording")


def test_desktop_app_includes_device_status_visual() -> None:
    assert _DEVICE_ASSET.is_file()


async def test_startup_voice_announces_online_without_a_repeated_greeting() -> None:
    speaker = AsyncMock()

    await _speak_startup_sequence(speaker, VoiceSettings())

    assert speaker.speak.await_args_list[0].args == (_STARTUP_ANNOUNCEMENT, VoiceSettings())
    assert speaker.speak.await_count == 1
