"""Integration test: a scripted multi-turn conversation through the full
core loop, with a stub LLM standing in for Ollama so this runs in CI
without any local model or network access.
"""
from atlas.core.assistant.core import AssistantCore
from atlas.core.llm.base import LLMProvider, LLMResponse
from atlas.core.memory.sqlite_store import SQLiteMemoryStore
from atlas.core.tools.registry import ToolRegistry


class _ScriptedLLM(LLMProvider):
    def __init__(self, replies: list[str]):
        self._replies = iter(replies)

    async def generate(self, messages, *, tools=None):
        return LLMResponse(content=next(self._replies))

    async def is_available(self):
        return True


async def test_multi_turn_conversation(tmp_path):
    memory = SQLiteMemoryStore(tmp_path / "memory.db")
    core = AssistantCore(
        assistant_name="Atlas",
        llm=_ScriptedLLM(["Hi! How can I help?", "Sure, noted."]),
        memory=memory,
        tools=ToolRegistry(),
    )

    first = await core.handle_message("hello")
    second = await core.handle_message("remember that I like tea")

    assert first == "Hi! How can I help?"
    assert second == "Sure, noted."

    history = await memory.recent_turns(10)
    assert len(history) == 4
    assert [t.role for t in history] == ["user", "assistant", "user", "assistant"]


async def test_forget_clears_memory(tmp_path):
    memory = SQLiteMemoryStore(tmp_path / "memory.db")
    await memory.add_turn("user", "secret")
    await memory.clear()
    assert await memory.recent_turns(10) == []
