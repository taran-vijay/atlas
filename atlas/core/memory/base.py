"""Memory subsystem interface.

V1 only implements rolling conversation history. The interface is shaped so
a later semantic/vector layer can be added (see docs/roadmap.md) without
changing anything in core/assistant.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from atlas.core.tools.base import ToolResult


@dataclass
class MemoryTurn:
    role: str
    content: str
    timestamp: float


@dataclass
class SavedMemory:
    id: int
    content: str
    created_at: float


@dataclass
class ActionRecord:
    id: int
    tool_name: str
    summary: str
    outcome: str
    timestamp: float


@dataclass(frozen=True)
class CommunicationProfile:
    """A small, local-only summary of how the user tends to communicate."""

    response_style: str = "balanced"
    tone: str = "neutral"


@dataclass(frozen=True)
class VoiceSettings:
    enabled: bool = True
    engine: str = "neural"
    neural_voice: str = "male_ryan"
    voice: str = "male_alex"


class MemoryStore(ABC):
    @abstractmethod
    async def add_turn(self, role: str, content: str) -> None:
        ...

    @abstractmethod
    async def recent_turns(self, limit: int) -> list[MemoryTurn]:
        ...

    @abstractmethod
    async def clear(self) -> None:
        """Delete all stored memory. Backs the 'forget that' user command."""

    @abstractmethod
    async def add_memory(self, content: str) -> SavedMemory:
        """Persist one fact the user explicitly asked Atlas to remember."""

    @abstractmethod
    async def list_memories(self, limit: int = 20) -> list[SavedMemory]:
        """Return the user's saved long-term memories, oldest first."""

    @abstractmethod
    async def forget_memory(self, content: str) -> bool:
        """Delete one exact saved memory. Return whether a row was removed."""

    @abstractmethod
    async def clear_memories(self) -> None:
        """Delete every saved long-term memory while preserving conversation history."""

    @abstractmethod
    async def record_action(
        self, tool_name: str, arguments: dict[str, Any], result: ToolResult
    ) -> None:
        """Persist a privacy-preserving record of a confirmation-gated action."""

    @abstractmethod
    async def recent_actions(self, limit: int = 50) -> list[ActionRecord]:
        """Return the newest recorded action outcomes first."""

    @abstractmethod
    async def clear_actions(self) -> None:
        """Delete action history without changing conversation or saved memories."""

    @abstractmethod
    async def observe_communication_style(self, user_input: str) -> CommunicationProfile:
        """Update and return a derived local communication preference, never raw text."""

    @abstractmethod
    async def get_communication_profile(self) -> CommunicationProfile:
        """Return the local, derived communication preference."""

    @abstractmethod
    async def clear_communication_profile(self) -> None:
        """Reset all inferred communication preferences."""

    @abstractmethod
    async def get_voice_settings(self) -> VoiceSettings:
        """Return the user's local speech preferences."""

    @abstractmethod
    async def save_voice_settings(self, settings: VoiceSettings) -> None:
        """Persist the user's local speech preferences."""
