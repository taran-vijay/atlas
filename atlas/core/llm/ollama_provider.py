"""Ollama-backed LLMProvider.

Ollama exposes a stable local HTTP API and handles model management, so this
implementation is intentionally thin: it translates between Atlas's
ChatMessage/LLMResponse types and Ollama's /api/chat endpoint.
"""
from __future__ import annotations

from typing import Any

import httpx

from atlas.core.llm.base import ChatMessage, LLMProvider, LLMResponse


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        host: str,
        model: str,
        *,
        temperature: float = 0.4,
        timeout: float = 60.0,
    ) -> None:
        self._host = host.rstrip("/")
        self._model = model
        self._temperature = temperature
        self._timeout = timeout

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {"temperature": self._temperature},
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{self._host}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        message = data.get("message", {})
        return LLMResponse(
            content=message.get("content", ""),
            tool_calls=message.get("tool_calls", []) or [],
            raw=data,
        )

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self._host}/api/tags")
                return resp.status_code == 200
        except httpx.HTTPError:
            return False
