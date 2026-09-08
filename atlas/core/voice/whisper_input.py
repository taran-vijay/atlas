"""Local push-to-talk recording and whisper.cpp transcription for macOS."""
from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
import threading
import wave
from collections.abc import Callable
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


class WakePhraseListener:
    """Continuously detect ``Hey Atlas`` locally with whisper.cpp's microphone mode."""

    def __init__(self, recognizer: WhisperCppRecognizer) -> None:
        self._recognizer = recognizer
        self._stop_event = threading.Event()
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def is_ready(self) -> bool:
        return self._recognizer.model_path.is_file() and shutil.which("whisper-stream") is not None

    def start(self, on_wake: Callable[[], None]) -> bool:
        if not self.is_ready() or self.is_running():
            return False
        self._stop_event.clear()
        threading.Thread(target=self._run, args=(on_wake,), daemon=True).start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()

    def is_running(self) -> bool:
        with self._lock:
            return self._process is not None and self._process.poll() is None

    def _run(self, on_wake: Callable[[], None]) -> None:
        command = [
            "whisper-stream",
            "--model",
            str(self._recognizer.model_path),
            "--language",
            "en",
            "--threads",
            "2",
            "--step",
            "1250",
            "--length",
            "2500",
            "--max-tokens",
            "12",
            "--no-fallback",
        ]
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError:
            return
        with self._lock:
            self._process = process
        recent = ""
        assert process.stdout is not None
        try:
            for line in process.stdout:
                if self._stop_event.is_set():
                    return
                recent = f"{recent} {line}"[-240:]
                if _contains_wake_phrase(recent):
                    on_wake()
                    return
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            with self._lock:
                if self._process is process:
                    self._process = None


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


def normalize_voice_transcript(transcript: str) -> str:
    """Repair only unambiguous command-style recognition slips before dispatch."""
    cleaned = " ".join(transcript.split())
    # A common phonetic confusion: "explain" becomes "blame" in short commands.
    corrected = re.fullmatch(r"blame\s+(.+?)\s+to\s+me[.!?]*", cleaned, re.IGNORECASE)
    if corrected is not None:
        return f"Explain {corrected.group(1)} to me."
    return cleaned


def split_wake_phrase(transcript: str) -> tuple[bool, str]:
    """Recognize a local 'Hey Atlas' wake phrase and return any following request."""
    cleaned = " ".join(transcript.split())
    match = re.match(r"^(?:hey|hi|hello)\s+atlas(?:[,.! ]+|$)(.*)$", cleaned, re.IGNORECASE)
    if match is None:
        return False, cleaned
    return True, match.group(1).strip(" ,.!?")


def is_ambiguous_voice_transcript(transcript: str) -> bool:
    """Reject only clear non-speech artifacts; legitimate short commands remain valid."""
    words = re.findall(r"[A-Za-z]+", transcript)
    if not words:
        return True
    if any(len(word) > 32 for word in words):
        return True
    normalized = [word.casefold() for word in words]
    return len(normalized) >= 3 and len(set(normalized)) == 1


def _contains_wake_phrase(text: str) -> bool:
    return re.search(r"\b(?:hey|hi|hello)\s+atlas\b", text, re.IGNORECASE) is not None


def _transcription_threads() -> int:
    """Use enough cores for a quick command without monopolizing the Mac."""
    return max(2, min(6, (os.cpu_count() or 4) // 2))


def _touch_file(path: Path) -> None:
    """Read in chunks so macOS can cache the small command model before first use."""
    with path.open("rb") as model:
        while model.read(1_048_576):
            pass
