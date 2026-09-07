"""On-device neural speech through a locally installed Piper voice model."""
from __future__ import annotations

import asyncio
import logging
import platform
import re
import shutil
import sys
import tempfile
import threading
import wave
from collections.abc import Callable
from pathlib import Path

from atlas.core.memory.base import VoiceSettings
from atlas.core.voice.macos_speaker import MacOSSpeaker, _speech_text

_LOGGER = logging.getLogger(__name__)
NEURAL_VOICE_OPTIONS = {
    "male_ryan": ("Ryan", "Adult male · deep, high-quality", "en_US-ryan-high.onnx"),
    "male_joe": ("Joe", "Adult male · natural, calm", "en_US-joe-medium.onnx"),
    "male_hfc": ("HFC Male", "Adult male · clear, measured", "en_US-hfc_male-medium.onnx"),
    "female_amy": ("Amy", "Adult female · warm, natural", "en_US-amy-medium.onnx"),
    "female_lessac": ("Lessac", "Adult female · clear, high-quality", "en_US-lessac-high.onnx"),
    "female_hfc": (
        "HFC Female",
        "Adult female · composed, articulate",
        "en_US-hfc_female-medium.onnx",
    ),
}


class PiperSpeaker:
    """Synthesize and play a Piper WAV file without sending text off-device."""

    def __init__(self, models_dir: Path) -> None:
        self._models_dir = models_dir.expanduser()
        self._speaking = threading.Lock()

    async def speak(
        self,
        text: str,
        settings: VoiceSettings,
        on_progress: Callable[[str], None] | None = None,
    ) -> bool:
        if not settings.enabled or platform.system() != "Darwin":
            return False
        spoken_text = _speech_text(text)
        executable = self._piper_executable()
        model_path = self.model_path(settings.neural_voice)
        if not spoken_text or executable is None or not model_path.is_file():
            return False
        if not self._speaking.acquire(blocking=False):
            return False

        audio_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output:
                audio_path = Path(output.name)
            process = await asyncio.create_subprocess_exec(
                executable,
                "--model",
                str(model_path),
                "--output_file",
                str(audio_path),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(
                    process.communicate(spoken_text.encode("utf-8")), timeout=90
                )
            except TimeoutError:
                process.terminate()
                await process.wait()
                _LOGGER.warning("neural_voice_synthesis_timed_out")
                return False
            if process.returncode != 0 or not audio_path.is_file() or audio_path.stat().st_size == 0:
                _LOGGER.warning("neural_voice_synthesis_failed error=%s", stderr.decode(errors="replace"))
                return False

            duration = _wav_duration(audio_path)
            player = await asyncio.create_subprocess_exec(
                "afplay",
                str(audio_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            progress = (
                asyncio.create_task(_emit_timed_progress(spoken_text, duration, on_progress))
                if on_progress is not None
                else None
            )
            try:
                await asyncio.wait_for(player.communicate(), timeout=max(duration + 15, 30))
            except TimeoutError:
                player.terminate()
                await player.wait()
                _LOGGER.warning("neural_voice_playback_timed_out")
                return False
            if progress is not None:
                await progress
            return player.returncode == 0
        except OSError:
            _LOGGER.exception("neural_voice_output_failed")
            return False
        finally:
            if audio_path is not None:
                audio_path.unlink(missing_ok=True)
            self._speaking.release()

    @staticmethod
    def _piper_executable() -> str | None:
        """Prefer Piper in the active Python environment, then PATH."""
        bundled = Path(sys.executable).with_name("piper")
        if bundled.is_file():
            return str(bundled)
        return shutil.which("piper")

    def model_path(self, voice_id: str) -> Path:
        """Return the fixed local path for a supported, user-selected voice."""
        _, _, filename = NEURAL_VOICE_OPTIONS.get(voice_id, NEURAL_VOICE_OPTIONS["male_ryan"])
        return self._models_dir / filename

    def is_ready(self, voice_id: str) -> bool:
        return self.model_path(voice_id).is_file()


class LocalVoiceSpeaker:
    """Use neural speech when configured; retain macOS speech as a local fallback."""

    def __init__(self, models_dir: Path) -> None:
        self._neural = PiperSpeaker(models_dir)
        self._system = MacOSSpeaker()

    def is_neural_voice_ready(self, voice_id: str) -> bool:
        return self._neural.is_ready(voice_id)

    async def speak(
        self,
        text: str,
        settings: VoiceSettings,
        on_progress: Callable[[str], None] | None = None,
    ) -> bool:
        if settings.engine == "neural":
            if await self._neural.speak(text, settings, on_progress):
                return True
            _LOGGER.info("neural_voice_unavailable_using_macos_fallback")
        return await self._system.speak(text, settings, on_progress)


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / audio.getframerate()


async def _emit_timed_progress(
    text: str, duration: float, callback: Callable[[str], None]
) -> None:
    """Render text as the generated audio plays, using its real WAV duration."""
    words = re.findall(r"\S+\s*", text)
    if not words:
        return
    seconds_per_word = max(duration, 0.1) / len(words)
    for index in range(0, len(words), 2):
        chunk = "".join(words[index : index + 2])
        callback(chunk)
        await asyncio.sleep(seconds_per_word * len(words[index : index + 2]))
