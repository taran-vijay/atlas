from unittest.mock import AsyncMock, patch

from atlas.core.memory.base import VoiceSettings
from atlas.core.voice.macos_speaker import MacOSSpeaker, _speech_text


class _Process:
    returncode = 0

    def __init__(self) -> None:
        self.communicate = AsyncMock(return_value=(b"", b""))


def test_speech_text_removes_common_markdown() -> None:
    assert _speech_text("## *Atlas* says `hello`") == "Atlas says hello"


async def test_male_profile_uses_a_deeper_macos_voice() -> None:
    speaker = MacOSSpeaker()
    speaker._available_voices = {"Alex"}
    process = _Process()
    with (
        patch("atlas.core.voice.macos_speaker.platform.system", return_value="Darwin"),
        patch(
            "atlas.core.voice.macos_speaker.asyncio.create_subprocess_exec",
            return_value=process,
        ) as spawn,
    ):
        await speaker.speak("System ready.", VoiceSettings(enabled=True, voice="male"))

    assert spawn.await_args is not None
    assert spawn.await_args.args == ("say", "-v", "Alex", "-r", "165", "System ready.")


async def test_voice_can_be_disabled_without_launching_speech() -> None:
    speaker = MacOSSpeaker()
    with patch("atlas.core.voice.macos_speaker.asyncio.create_subprocess_exec") as spawn:
        await speaker.speak("System ready.", VoiceSettings(enabled=False, voice="female"))

    spawn.assert_not_called()
