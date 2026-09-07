from pathlib import Path

from atlas.core.memory.base import VoiceSettings
from atlas.core.memory.sqlite_store import SQLiteMemoryStore
from atlas.core.tools.base import ToolResult


async def test_sqlite_store_keeps_explicit_memories_separate_from_turns(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    store = SQLiteMemoryStore(db_path)
    await store.add_turn("user", "hello")
    saved = await store.add_memory("my name is Taran")

    assert saved.content == "my name is Taran"
    assert [memory.content for memory in await store.list_memories()] == ["my name is Taran"]
    assert [turn.content for turn in await store.recent_turns(10)] == ["hello"]

    assert await store.forget_memory("my name is Taran") is True
    assert await store.list_memories() == []


async def test_sqlite_store_records_actions_without_clipboard_contents(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")

    await store.record_action(
        "desktop.copy_to_clipboard", {"text": "private clipboard value"}, ToolResult(True, "Copied")
    )
    actions = await store.recent_actions()

    assert len(actions) == 1
    assert actions[0].outcome == "COMPLETED"
    assert actions[0].summary == "Copy to clipboard: 23 characters"
    await store.clear_actions()
    assert await store.recent_actions() == []


async def test_sqlite_store_persists_voice_settings(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")
    assert await store.get_voice_settings() == VoiceSettings()

    await store.save_voice_settings(VoiceSettings(enabled=False, voice="female"))

    assert await store.get_voice_settings() == VoiceSettings(enabled=False, voice="female")
