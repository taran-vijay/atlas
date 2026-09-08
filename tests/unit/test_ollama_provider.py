from __future__ import annotations

from typing import Any, Self
from unittest.mock import patch

from atlas.core.llm.base import ChatMessage
from atlas.core.llm.ollama_provider import OllamaProvider


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"message": {"content": "Ready"}}


class _Client:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    async def post(self, url: str, *, json: dict[str, Any]) -> _Response:
        self.payload = json
        return _Response()


async def test_provider_sends_bounded_resource_options_to_ollama() -> None:
    client = _Client()
    provider = OllamaProvider(
        "http://localhost:11434",
        "atlas-model",
        context_tokens=2048,
        max_response_tokens=256,
        keep_alive="3m",
    )
    with patch("atlas.core.llm.ollama_provider.httpx.AsyncClient", return_value=client):
        response = await provider.generate([ChatMessage(role="user", content="Hello")])

    assert response.content == "Ready"
    assert client.payload is not None
    assert client.payload["options"] == {
        "temperature": 0.4,
        "num_ctx": 2048,
        "num_predict": 256,
    }
    assert client.payload["keep_alive"] == "3m"
    assert client.payload["think"] is False


async def test_provider_preloads_the_local_model() -> None:
    client = _Client()
    provider = OllamaProvider("http://localhost:11434", "atlas-model", keep_alive="15m")

    with patch("atlas.core.llm.ollama_provider.httpx.AsyncClient", return_value=client):
        await provider.warm()

    assert client.payload == {"model": "atlas-model", "stream": False, "keep_alive": "15m"}
