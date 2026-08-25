"""Abstract interface every LLM backend must implement.

AssistantCore depends only on this interface, never on a specific provider --
swapping Ollama for llama.cpp, MLX, or anything else should never require
touching core/assistant.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessage:
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] | None = None


class LLMProvider(ABC):
    """Interface for any local (or remote) chat-completion backend."""

    @abstractmethod
    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Produce the next assistant turn given the conversation so far."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Return True if the backend is reachable and ready to serve requests."""
