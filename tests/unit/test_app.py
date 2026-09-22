import inspect
from unittest.mock import AsyncMock

import atlas.app as desktop_app
from atlas.app import (
    _DEVICE_ASSET,
    _STARTUP_ANNOUNCEMENT,
    AtlasDesktopApp,
    ConnectionScreen,
    _create_assistant,
    _outcome_report,
    _speak_startup_sequence,
)
from atlas.core.memory.base import OutcomeSummary, VoiceSettings


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


def test_desktop_app_uses_only_supported_tk_text_options() -> None:
    assert "disabledforeground" not in inspect.getsource(desktop_app)


def test_outcome_report_uses_real_measurements_without_private_content() -> None:
    report = _outcome_report(
        OutcomeSummary(
            response_count=4,
            successful_response_count=3,
            average_response_ms=750,
            p95_response_ms=1_800,
            tool_call_count=2,
            successful_tool_call_count=1,
            average_tool_ms=120,
            voice_transcription_count=1,
            successful_voice_transcription_count=1,
            average_voice_transcription_ms=860,
        )
    )

    assert "3 of 4 completed" in report
    assert "750 ms" in report
    assert "1.8 s" in report
    assert "1 of 2 completed (50%)" in report


async def test_startup_voice_announces_online_without_a_repeated_greeting() -> None:
    speaker = AsyncMock()

    await _speak_startup_sequence(speaker, VoiceSettings())

    assert speaker.speak.await_args_list[0].args == (_STARTUP_ANNOUNCEMENT, VoiceSettings())
    assert speaker.speak.await_count == 1
