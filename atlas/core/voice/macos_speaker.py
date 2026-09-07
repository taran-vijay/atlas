"""Non-blocking macOS speech output using the built-in ``say`` command."""
from __future__ import annotations

import asyncio
import logging
import platform
import re
import threading
from collections.abc import Callable

from atlas.core.memory.base import VoiceSettings

_LOGGER = logging.getLogger(__name__)
_MAX_SPOKEN_CHARACTERS = 3_000
VOICE_OPTIONS = {
    "male_alex": ("Alex", "Adult male · balanced, warm", ("Alex", "Daniel", "Eddy"), 195),
    "male_daniel": ("Daniel", "Adult male · clear, composed", ("Daniel", "Alex", "Eddy"), 200),
    "male_eddy": ("Eddy", "Adult male · energetic, conversational", ("Eddy", "Alex", "Daniel"), 205),
    "female_samantha": ("Samantha", "Adult female · natural, expressive", ("Samantha", "Ava", "Karen"), 205),
    "female_ava": ("Ava", "Adult female · bright, clear", ("Ava", "Samantha", "Karen"), 210),
    "female_karen": ("Karen", "Adult female · calm, articulate", ("Karen", "Samantha", "Ava"), 200),
}


class MacOSSpeaker:
    """Speak one completed reply without blocking Atlas or overlapping speech."""

    def __init__(self) -> None:
        self._speaking = threading.Lock()
        self._available_voices: set[str] | None = None

    async def speak(
        self,
        text: str,
        settings: VoiceSettings,
        on_progress: Callable[[str], None] | None = None,
    ) -> bool:
        if not settings.enabled or platform.system() != "Darwin":
            return False
        spoken_text = _speech_text(text)
        if not spoken_text or not self._speaking.acquire(blocking=False):
            return False
        try:
            voice, rate = await self._voice_profile(settings.voice)
            command = ["say"]
            if voice is not None:
                command.extend(["-v", voice])
            command.extend(["-r", str(rate), spoken_text])
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            progress = (
                asyncio.create_task(_emit_progress(spoken_text, rate, on_progress))
                if on_progress is not None
                else None
            )
            try:
                await asyncio.wait_for(process.communicate(), timeout=60)
            except TimeoutError:
                process.terminate()
                await process.wait()
                if progress is not None:
                    progress.cancel()
                _LOGGER.warning("voice_output_timed_out")
                return False
            if progress is not None:
                await progress
            return process.returncode == 0
        except OSError:
            _LOGGER.exception("voice_output_failed")
            return False
        finally:
            self._speaking.release()

    async def _voice_profile(self, requested_voice: str) -> tuple[str | None, int]:
        _, _, candidates, rate = VOICE_OPTIONS.get(requested_voice, VOICE_OPTIONS["male_alex"])
        voices = await self._system_voices()
        return next((voice for voice in candidates if voice in voices), None), rate

    async def _system_voices(self) -> set[str]:
        if self._available_voices is not None:
            return self._available_voices
        try:
            process = await asyncio.create_subprocess_exec(
                "say", "-v", "?", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
            )
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=5)
        except (OSError, TimeoutError):
            return set()
        self._available_voices = {
            line.split(maxsplit=1)[0] for line in stdout.decode(errors="replace").splitlines() if line
        }
        return self._available_voices


def _speech_text(text: str) -> str:
    """Make common Markdown reply syntax pleasant to hear, with a fixed work bound."""
    normalized = re.sub(r"[`*_#]", "", text).replace("•", "")
    return normalized.strip()[:_MAX_SPOKEN_CHARACTERS]


async def _emit_progress(text: str, rate: int, callback: Callable[[str], None]) -> None:
    """Advance the transcript at the same conversational pace used by ``say``."""
    words = re.findall(r"\S+\s*", text)
    seconds_per_word = 60 / rate
    for index in range(0, len(words), 2):
        chunk = "".join(words[index:index + 2])
        callback(chunk)
        await asyncio.sleep(seconds_per_word * len(words[index:index + 2]))
