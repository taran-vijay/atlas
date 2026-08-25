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
