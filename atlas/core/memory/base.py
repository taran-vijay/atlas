"""Memory subsystem interface.

V1 only implements rolling conversation history. The interface is shaped so
a later semantic/vector layer can be added (see docs/roadmap.md) without
changing anything in core/assistant.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


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
