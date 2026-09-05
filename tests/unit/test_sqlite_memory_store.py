from pathlib import Path

from atlas.core.memory.sqlite_store import SQLiteMemoryStore


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
