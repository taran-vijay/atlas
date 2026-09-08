from pathlib import Path
from unittest.mock import patch

from atlas.core.voice.whisper_input import WhisperCppRecognizer, _clean_transcript, _wav_bytes


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
