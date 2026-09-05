"""SQLite-backed MemoryStore -- the default local persistence for V1.

A single local file, no server, easy for a user to inspect or delete
(`rm ~/.atlas/memory.db` works, and so does a future 'forget that' voice
command). sqlite3 calls here block briefly on each turn; that's an
acceptable tradeoff for V1's small rolling history -- revisit if a heavier
memory backend lands in a later milestone.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from atlas.core.memory.base import MemoryStore, MemoryTurn, SavedMemory

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL
);
"""


class SQLiteMemoryStore(MemoryStore):
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    async def add_turn(self, role: str, content: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO turns (role, content, timestamp) VALUES (?, ?, ?)",
                (role, content, time.time()),
            )

    async def recent_turns(self, limit: int) -> list[MemoryTurn]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT role, content, timestamp FROM turns ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [MemoryTurn(role=r, content=c, timestamp=t) for r, c, t in reversed(rows)]

    async def clear(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM turns")

    async def add_memory(self, content: str) -> SavedMemory:
        timestamp = time.time()
        normalized = content.strip()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO memories (content, created_at) VALUES (?, ?)",
                (normalized, timestamp),
            )
            row = conn.execute(
                "SELECT id, content, created_at FROM memories WHERE content = ?", (normalized,)
            ).fetchone()
        assert row is not None
        return SavedMemory(id=row[0], content=row[1], created_at=row[2])

    async def list_memories(self, limit: int = 20) -> list[SavedMemory]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, content, created_at FROM memories ORDER BY id ASC LIMIT ?", (limit,)
            ).fetchall()
        return [SavedMemory(id=row[0], content=row[1], created_at=row[2]) for row in rows]

    async def forget_memory(self, content: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM memories WHERE content = ?", (content.strip(),))
        return cursor.rowcount > 0

    async def clear_memories(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM memories")
