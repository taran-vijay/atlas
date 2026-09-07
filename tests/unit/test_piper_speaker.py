import wave
from pathlib import Path
from unittest.mock import AsyncMock, patch

from atlas.core.memory.base import VoiceSettings
from atlas.core.voice.piper_speaker import LocalVoiceSpeaker, PiperSpeaker, _emit_timed_progress


class _Process:
    returncode = 0

    def __init__(self) -> None:
        self.communicate = AsyncMock(return_value=(b"", b""))


async def test_neural_speaker_generates_and_plays_a_local_wav(tmp_path: Path) -> None:
    model = tmp_path / "en_US-ryan-high.onnx"
    model.write_bytes(b"model")
    speaker = PiperSpeaker(tmp_path)
    piper_process = _Process()
    player_process = _Process()

    async def spawn(*command: str, **_: object) -> _Process:
        if command[0] == "piper":
            output_path = Path(command[command.index("--output_file") + 1])
            with wave.open(str(output_path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(22_050)
                output.writeframes(b"\x00\x00" * 2_205)
            return piper_process
        return player_process

    with (
        patch("atlas.core.voice.piper_speaker.platform.system", return_value="Darwin"),
        patch.object(PiperSpeaker, "_piper_executable", return_value="piper"),
        patch("atlas.core.voice.piper_speaker.asyncio.create_subprocess_exec", side_effect=spawn) as run,
        patch("atlas.core.voice.piper_speaker.asyncio.sleep", new_callable=AsyncMock),
    ):
        assert await speaker.speak("Atlas is ready.", VoiceSettings()) is True

    assert run.await_args_list[0].args[:3] == ("piper", "--model", str(model))
    assert run.await_args_list[1].args[0] == "afplay"


async def test_neural_engine_falls_back_to_macos_when_model_is_not_ready(tmp_path: Path) -> None:
    speaker = LocalVoiceSpeaker(tmp_path / "not-installed.onnx")
    with patch.object(speaker._system, "speak", new=AsyncMock(return_value=True)) as fallback:
        assert await speaker.speak("Atlas is ready.", VoiceSettings(engine="neural")) is True

    fallback.assert_awaited_once()


def test_neural_voice_profiles_resolve_to_distinct_male_and_female_models(tmp_path: Path) -> None:
    speaker = PiperSpeaker(tmp_path)

    assert speaker.model_path("male_ryan").name == "en_US-ryan-high.onnx"
    assert speaker.model_path("male_joe").name == "en_US-joe-medium.onnx"
    assert speaker.model_path("female_amy").name == "en_US-amy-medium.onnx"
    assert speaker.model_path("female_hfc").name == "en_US-hfc_female-medium.onnx"


async def test_neural_progress_uses_the_generated_audio_duration() -> None:
    fragments: list[str] = []
    with patch("atlas.core.voice.piper_speaker.asyncio.sleep", new_callable=AsyncMock) as sleep:
        await _emit_timed_progress("Atlas is ready now.", 2.0, fragments.append)

    assert fragments == ["Atlas is ", "ready now."]
    assert sleep.await_args_list[0].args == (1.0,)
