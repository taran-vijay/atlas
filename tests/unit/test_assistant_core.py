from typing import Any

from atlas.core.assistant.core import AssistantCore
from atlas.core.llm.base import ChatMessage, LLMProvider, LLMResponse
from atlas.core.memory.base import MemoryStore, MemoryTurn
from atlas.core.tools.registry import ToolRegistry


class _StubLLM(LLMProvider):
    def __init__(self, reply: str) -> None:
        self._reply = reply

    async def generate(
        self, messages: list[ChatMessage], *, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        return LLMResponse(content=self._reply)

    async def is_available(self) -> bool:
        return True


class _InMemoryStore(MemoryStore):
    def __init__(self) -> None:
        self._turns: list[MemoryTurn] = []

    async def add_turn(self, role: str, content: str) -> None:
        self._turns.append(MemoryTurn(role=role, content=content, timestamp=0.0))

    async def recent_turns(self, limit: int) -> list[MemoryTurn]:
        return self._turns[-limit:]

    async def clear(self) -> None:
        self._turns.clear()


async def test_handle_message_returns_llm_reply_and_persists_turns() -> None:
    memory = _InMemoryStore()
    core = AssistantCore(
        assistant_name="Atlas",
        llm=_StubLLM("hello there"),
        memory=memory,
        tools=ToolRegistry(),
    )
    reply = await core.handle_message("hi")
    assert reply == "hello there"

    history = await memory.recent_turns(10)
    assert [t.role for t in history] == ["user", "assistant"]
