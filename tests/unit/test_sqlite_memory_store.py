import sqlite3
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

    await store.save_voice_settings(
        VoiceSettings(
            enabled=False,
            engine="system",
            neural_voice="female_amy",
            voice="female_samantha",
        )
    )

    assert await store.get_voice_settings() == VoiceSettings(
        enabled=False,
        engine="system",
        neural_voice="female_amy",
        voice="female_samantha",
    )


async def test_sqlite_store_derives_and_resets_communication_style_locally(tmp_path: Path) -> None:
    store = SQLiteMemoryStore(tmp_path / "memory.db")

    for message in ("hey", "sounds good", "can you help"):
        profile = await store.observe_communication_style(message)

    assert profile.response_style == "concise"
    assert profile.tone == "casual"
    await store.clear_communication_profile()
    assert (await store.get_communication_profile()).response_style == "balanced"


async def test_sqlite_store_migrates_voice_settings_from_v02(tmp_path: Path) -> None:
    db_path = tmp_path / "memory.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE voice_settings ("
            "id INTEGER PRIMARY KEY CHECK (id = 1), enabled INTEGER NOT NULL, voice TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO voice_settings (id, enabled, voice) VALUES (1, 1, 'female_ava')"
        )

    store = SQLiteMemoryStore(db_path)

    assert await store.get_voice_settings() == VoiceSettings(
        enabled=True, engine="neural", neural_voice="male_ryan", voice="female_ava"
    )
