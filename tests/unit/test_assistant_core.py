from atlas.core.assistant.core import AssistantCore
from atlas.core.llm.base import LLMProvider, LLMResponse
from atlas.core.memory.base import MemoryStore, MemoryTurn
from atlas.core.tools.registry import ToolRegistry


class _StubLLM(LLMProvider):
    def __init__(self, reply: str):
        self._reply = reply

    async def generate(self, messages, *, tools=None):
        return LLMResponse(content=self._reply)

    async def is_available(self):
        return True


class _InMemoryStore(MemoryStore):
    def __init__(self):
        self._turns: list[MemoryTurn] = []

    async def add_turn(self, role, content):
        self._turns.append(MemoryTurn(role=role, content=content, timestamp=0.0))

    async def recent_turns(self, limit):
        return self._turns[-limit:]

    async def clear(self):
        self._turns.clear()


async def test_handle_message_returns_llm_reply_and_persists_turns():
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
