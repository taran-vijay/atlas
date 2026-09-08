"""Local push-to-talk recording and whisper.cpp transcription for macOS."""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import wave
from pathlib import Path
from typing import Any


class VoiceInputError(RuntimeError):
    """A local microphone or transcription dependency is unavailable."""


class WhisperCppRecognizer:
    """Use a local whisper.cpp binary; audio is never sent to a service."""

    def __init__(self, models_dir: Path, model_name: str = "ggml-tiny.en.bin") -> None:
        self._models_dir = models_dir.expanduser()
        self._model_name = model_name

    @property
    def model_path(self) -> Path:
        return self._models_dir / self._model_name

    def is_ready(self) -> bool:
        return self._executable() is not None and self.model_path.is_file()

    async def prewarm(self) -> None:
        """Warm the local model's file cache without competing with the UI thread."""
        if self.model_path.is_file():
            await asyncio.to_thread(_touch_file, self.model_path)

    async def transcribe(self, wav_data: bytes) -> str:
        executable = self._executable()
        if executable is None:
            raise VoiceInputError("Local whisper.cpp is not installed. Run scripts/setup_voice_input.sh.")
        if not self.model_path.is_file():
            raise VoiceInputError("The local speech model is not installed. Run scripts/setup_voice_input.sh.")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as source:
            source.write(wav_data)
            source_path = Path(source.name)
        try:
            process = await asyncio.create_subprocess_exec(
                executable,
                "--model",
                str(self.model_path),
                "--file",
                str(source_path),
                "--no-timestamps",
                "--language",
                "en",
                "--threads",
                str(_transcription_threads()),
                "--no-fallback",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=90)
            if process.returncode != 0:
                raise VoiceInputError("Local speech transcription failed. Please try again.")
            return _clean_transcript(stdout.decode(errors="replace"))
        except TimeoutError as exc:
            raise VoiceInputError("Local speech transcription took too long. Please try again.") from exc
        finally:
            source_path.unlink(missing_ok=True)

    @staticmethod
    def _executable() -> str | None:
        return shutil.which("whisper-cli") or shutil.which("whisper-cpp")


class PushToTalkRecorder:
    """Record only while the UI button is held, then hand a WAV to Whisper."""

    def __init__(self, recognizer: WhisperCppRecognizer, sample_rate: int = 16_000) -> None:
        self._recognizer = recognizer
        self._sample_rate = sample_rate
        self._stream: Any | None = None
        self._frames = bytearray()

    def is_ready(self) -> bool:
        return self._recognizer.is_ready() and _sounddevice() is not None

    def start(self) -> None:
        if self._stream is not None:
            return
        sounddevice = _sounddevice()
        if sounddevice is None:
            raise VoiceInputError("Microphone support is not installed. Run scripts/setup_voice_input.sh.")
        self._frames.clear()

        def capture(indata: Any, _: int, __: Any, ___: Any) -> None:
            self._frames.extend(bytes(indata))

        try:
            self._stream = sounddevice.RawInputStream(
                samplerate=self._sample_rate, channels=1, dtype="int16", callback=capture
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise VoiceInputError("Atlas could not access the microphone. Check macOS permissions.") from exc

    async def stop_and_transcribe(self) -> str:
        if self._stream is None:
            return ""
        self._stream.stop()
        self._stream.close()
        self._stream = None
        if not self._frames:
            return ""
        return await self._recognizer.transcribe(_wav_bytes(bytes(self._frames), self._sample_rate))

    async def prewarm(self) -> None:
        await self._recognizer.prewarm()


def _sounddevice() -> Any | None:
    try:
        import sounddevice  # type: ignore[import-untyped]
    except ImportError:
        return None
    return sounddevice


def _wav_bytes(frames: bytes, sample_rate: int) -> bytes:
    with tempfile.SpooledTemporaryFile() as output:
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(frames)
        output.seek(0)
        return output.read()


def _clean_transcript(output: str) -> str:
    """Keep user speech, excluding whisper.cpp's bracketed diagnostics."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return " ".join(line for line in lines if not line.startswith(("whisper_", "system_info:")))


def _transcription_threads() -> int:
    """Use enough cores for a quick command without monopolizing the Mac."""
    return max(2, min(6, (os.cpu_count() or 4) // 2))


def _touch_file(path: Path) -> None:
    """Read in chunks so macOS can cache the small command model before first use."""
    with path.open("rb") as model:
        while model.read(1_048_576):
            pass
