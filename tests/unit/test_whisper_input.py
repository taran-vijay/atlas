from pathlib import Path
from unittest.mock import patch

from atlas.core.voice import whisper_input
from atlas.core.voice.whisper_input import (
    PushToTalkRecorder,
    WhisperCppRecognizer,
    _clean_transcript,
    _wav_bytes,
    is_ambiguous_voice_transcript,
    normalize_voice_transcript,
)


def test_whisper_recognizer_requires_a_local_binary_and_model(tmp_path: Path) -> None:
    recognizer = WhisperCppRecognizer(tmp_path)

    with patch.object(WhisperCppRecognizer, "_executable", return_value="whisper-cli"):
        assert recognizer.is_ready() is False
    (tmp_path / "ggml-tiny.en.bin").write_bytes(b"model")
    with patch.object(WhisperCppRecognizer, "_executable", return_value="whisper-cli"):
        assert recognizer.is_ready() is True


def test_whisper_output_removes_diagnostic_lines() -> None:
    output = "system_info: local\nwhisper_init: ready\nHello Atlas\n"

    assert _clean_transcript(output) == "Hello Atlas"


def test_wav_builder_creates_a_valid_mono_pcm_wave() -> None:
    data = _wav_bytes(b"\x00\x00" * 16, 16_000)

    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WAVE"


def test_voice_transcript_repairs_only_an_unambiguous_phonetic_command_error() -> None:
    assert normalize_voice_transcript("Blame machine learning to me.") == "Explain machine learning to me."
    assert normalize_voice_transcript("Blame the printer for this") == "Blame the printer for this"


def test_clear_non_speech_artifacts_are_rejected_without_rejecting_short_commands() -> None:
    assert is_ambiguous_voice_transcript("") is True
    assert is_ambiguous_voice_transcript("blah blah blah") is True
    assert is_ambiguous_voice_transcript("Hi") is False


def test_voice_input_is_explicit_push_to_talk_without_a_background_listener() -> None:
    assert "held" in (PushToTalkRecorder.__doc__ or "").casefold()
    assert not hasattr(whisper_input, "WakePhraseListener")
