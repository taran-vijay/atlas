"""Voice component interfaces (Milestone 2).

These interfaces keep speech recognition and speech output independently
swappable while Atlas remains push-to-talk by design.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class SpeechRecognizer(ABC):
    @abstractmethod
    async def transcribe(self, audio: bytes) -> str:
        """Convert captured audio into text, entirely on-device."""


class SpeechSynthesizer(ABC):
    @abstractmethod
    async def speak(self, text: str) -> None:
        """Convert text to speech and play it, entirely on-device."""
