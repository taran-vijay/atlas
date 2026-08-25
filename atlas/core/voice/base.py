"""Voice component interfaces (Milestone 2).

No implementations yet -- these exist now so the assistant/voice boundary is
decided before any speech code is written, and so wake word, STT, and TTS
stay independently swappable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class WakeWordDetector(ABC):
    @abstractmethod
    async def listen_for_wake_word(self) -> None:
        """Block (asynchronously) until the configured wake phrase is detected."""


class SpeechRecognizer(ABC):
    @abstractmethod
    async def transcribe(self, audio: bytes) -> str:
        """Convert captured audio into text, entirely on-device."""


class SpeechSynthesizer(ABC):
    @abstractmethod
    async def speak(self, text: str) -> None:
        """Convert text to speech and play it, entirely on-device."""
