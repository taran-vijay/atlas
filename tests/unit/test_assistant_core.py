from typing import Any

from atlas.core.assistant.core import _NO_TOOL_RESPONSE_PROMPT, AssistantCore
from atlas.core.llm.base import ChatMessage, LLMProvider, LLMResponse
from atlas.core.memory.base import MemoryStore, MemoryTurn
from atlas.core.tools.base import PermissionLevel, Tool, ToolResult
from atlas.core.tools.registry import ToolRegistry
from atlas.core.tools.system_tools import GetProcessesTool


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


class _ScriptedLLM(LLMProvider):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = iter(responses)
        self.messages: list[list[ChatMessage]] = []
        self.tool_sets: list[list[dict[str, Any]] | None] = []

    async def generate(
        self, messages: list[ChatMessage], *, tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        self.messages.append(messages.copy())
        self.tool_sets.append(tools)
        return next(self._responses)

    async def is_available(self) -> bool:
        return True


class _StatusTool(Tool):
    def __init__(self, name: str, result: ToolResult) -> None:
        self.name = name
        self.description = name
        self.parameters: dict[str, Any] = {"type": "object"}
        self.permission = PermissionLevel.READ_ONLY
        self._result = result

    def validate_arguments(self, arguments: dict[str, Any]) -> None:
        if arguments:
            raise ValueError("does not accept arguments")

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        return self._result


def _tool_call(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"function": {"name": name, "arguments": arguments or {}}}


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


async def test_casual_message_does_not_offer_system_tools() -> None:
    memory = _InMemoryStore()
    llm = _ScriptedLLM([LLMResponse(content="Hello!")])
    registry = ToolRegistry()
    registry.register(_StatusTool("system.get_time", ToolResult(True, "10:00 AM.")))
    core = AssistantCore(
        assistant_name="Atlas",
        llm=llm,
        memory=memory,
        tools=registry,
    )

    reply = await core.handle_message("Hello, how are you?")

    assert reply == "Hello!"
    assert llm.tool_sets == [None]


async def test_casual_message_retries_as_plain_chat_after_spurious_tool_call() -> None:
    memory = _InMemoryStore()
    llm = _ScriptedLLM(
        [
            LLMResponse(content="", tool_calls=[_tool_call("system.get_time")]),
            LLMResponse(content="I am doing well—how can I help?"),
        ]
    )
    registry = ToolRegistry()
    registry.register(_StatusTool("system.get_time", ToolResult(True, "10:00 AM.")))
    core = AssistantCore(assistant_name="Atlas", llm=llm, memory=memory, tools=registry)

    reply = await core.handle_message("Hello, how are you?")

    assert reply == "I am doing well—how can I help?"
    assert llm.tool_sets == [None, None]
    assert llm.messages[1][-1].content == _NO_TOOL_RESPONSE_PROMPT


async def test_status_report_preserves_all_structured_tool_results() -> None:
    memory = _InMemoryStore()
    registry = ToolRegistry()
    registry.register(_StatusTool("system.get_battery", ToolResult(True, "Battery: 92%.", {"percentage": 92})))
    registry.register(_StatusTool("system.get_time", ToolResult(True, "10:00 AM.", {"time": "10:00"})))
    llm = _ScriptedLLM(
        [
            LLMResponse(
                content="",
                tool_calls=[_tool_call("system.get_battery"), _tool_call("system.get_time")],
            ),
            LLMResponse(content="Battery is 92%; current time is 10:00 AM."),
        ]
    )
    core = AssistantCore(assistant_name="Atlas", llm=llm, memory=memory, tools=registry)

    reply = await core.handle_message("Give me a quick status report.")

    assert reply == "Battery is 92%; current time is 10:00 AM."
    follow_up_messages = llm.messages[1]
    assert follow_up_messages[-3].metadata["tool_calls"] == [
        _tool_call("system.get_battery"),
        _tool_call("system.get_time"),
    ]
    assert '"percentage": 92' in follow_up_messages[-2].content
    assert '"time": "10:00"' in follow_up_messages[-1].content


async def test_failed_status_tool_cannot_be_filled_in_by_the_llm() -> None:
    memory = _InMemoryStore()
    registry = ToolRegistry()
    registry.register(
        _StatusTool("system.get_battery", ToolResult(False, "", error="Battery telemetry command failed."))
    )
    llm = _ScriptedLLM(
        [
            LLMResponse(content="", tool_calls=[_tool_call("system.get_battery")]),
            LLMResponse(content="Your battery is 100% and not charging."),
        ]
    )
    core = AssistantCore(assistant_name="Atlas", llm=llm, memory=memory, tools=registry)

    reply = await core.handle_message("What is my battery level?")

    assert "100%" not in reply
    assert "system.get_battery: unavailable" in reply
    assert "Battery telemetry command failed." in reply


async def test_malformed_process_arguments_return_a_safe_partial_reply() -> None:
    memory = _InMemoryStore()
    registry = ToolRegistry()
    registry.register(GetProcessesTool())
    llm = _ScriptedLLM(
        [
            LLMResponse(content="", tool_calls=[_tool_call("system.get_processes", {"limit": "five"})]),
            LLMResponse(content="Invented process list."),
        ]
    )
    core = AssistantCore(assistant_name="Atlas", llm=llm, memory=memory, tools=registry)

    reply = await core.handle_message("Show my top five processes.")

    assert "Invented process list." not in reply
    assert "unavailable" in reply
    assert "Invalid arguments" in reply
