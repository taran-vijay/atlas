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
from typing import Any

from atlas.core.memory.base import ActionRecord, MemoryStore, MemoryTurn, SavedMemory
from atlas.core.tools.base import ToolResult

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

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    summary TEXT NOT NULL,
    outcome TEXT NOT NULL,
    timestamp REAL NOT NULL
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

    async def record_action(
        self, tool_name: str, arguments: dict[str, Any], result: ToolResult
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO actions (tool_name, summary, outcome, timestamp) VALUES (?, ?, ?, ?)",
                (tool_name, _action_summary(tool_name, arguments), _action_outcome(result), time.time()),
            )

    async def recent_actions(self, limit: int = 50) -> list[ActionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, tool_name, summary, outcome, timestamp FROM actions "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [ActionRecord(id=row[0], tool_name=row[1], summary=row[2], outcome=row[3], timestamp=row[4]) for row in rows]

    async def clear_actions(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM actions")


def _action_outcome(result: ToolResult) -> str:
    if result.success:
        return "COMPLETED"
    if result.error == "User declined confirmation":
        return "DECLINED"
    return "FAILED"


def _action_summary(tool_name: str, arguments: dict[str, Any]) -> str:
    """Retain targets, never raw clipboard text or tool-result content."""
    if tool_name == "desktop.open_application":
        return f"Open application: {arguments.get('app', '')}"
    if tool_name == "desktop.open_file":
        return f"Open file: {arguments.get('path', '')}"
    if tool_name == "desktop.copy_to_clipboard":
        return f"Copy to clipboard: {len(str(arguments.get('text', '')))} characters"
    if tool_name == "filesystem.create_text_file":
        return f"Create text file: {arguments.get('path', '')}"
    if tool_name == "filesystem.create_folder":
        return f"Create folder: {arguments.get('path', '')}"
    if tool_name in {"filesystem.move_file", "filesystem.copy_file"}:
        return f"{tool_name.rsplit('.', maxsplit=1)[1].title()}: {arguments.get('source', '')} → {arguments.get('destination', '')}"
    if tool_name == "filesystem.rename_file":
        return f"Rename: {arguments.get('path', '')} → {arguments.get('new_name', '')}"
    if tool_name == "filesystem.move_to_trash":
        return f"Move to Trash: {arguments.get('path', '')}"
    return f"Action: {tool_name}"
