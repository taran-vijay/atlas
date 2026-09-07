"""Non-blocking macOS speech output using the built-in ``say`` command."""
from __future__ import annotations

import asyncio
import logging
import platform
import re
import threading

from atlas.core.memory.base import VoiceSettings

_LOGGER = logging.getLogger(__name__)
_MAX_SPOKEN_CHARACTERS = 3_000
_VOICE_PROFILES = {
    "male": (("Alex", "Eddy", "Daniel"), 165),
    "female": (("Samantha", "Ava", "Karen"), 190),
}


class MacOSSpeaker:
    """Speak one completed reply without blocking Atlas or overlapping speech."""

    def __init__(self) -> None:
        self._speaking = threading.Lock()
        self._available_voices: set[str] | None = None

    async def speak(self, text: str, settings: VoiceSettings) -> None:
        if not settings.enabled or platform.system() != "Darwin":
            return
        spoken_text = _speech_text(text)
        if not spoken_text or not self._speaking.acquire(blocking=False):
            return
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
            try:
                await asyncio.wait_for(process.communicate(), timeout=60)
            except TimeoutError:
                process.terminate()
                await process.wait()
                _LOGGER.warning("voice_output_timed_out")
        except OSError:
            _LOGGER.exception("voice_output_failed")
        finally:
            self._speaking.release()

    async def _voice_profile(self, requested_voice: str) -> tuple[str | None, int]:
        candidates, rate = _VOICE_PROFILES.get(requested_voice, _VOICE_PROFILES["male"])
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
