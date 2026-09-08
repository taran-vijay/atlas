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

from atlas.core.memory.base import (
    ActionRecord,
    CommunicationProfile,
    MemoryStore,
    MemoryTurn,
    SavedMemory,
    VoiceSettings,
)
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

CREATE TABLE IF NOT EXISTS voice_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled INTEGER NOT NULL,
    engine TEXT NOT NULL DEFAULT 'neural',
    neural_voice TEXT NOT NULL DEFAULT 'male_ryan',
    voice TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS communication_profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    message_count INTEGER NOT NULL DEFAULT 0,
    total_words INTEGER NOT NULL DEFAULT 0,
    short_message_count INTEGER NOT NULL DEFAULT 0,
    casual_message_count INTEGER NOT NULL DEFAULT 0
);
"""


class SQLiteMemoryStore(MemoryStore):
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            _migrate_voice_settings(conn)

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

    async def observe_communication_style(self, user_input: str) -> CommunicationProfile:
        """Store aggregate style signals only; the original message stays in the transcript."""
        words = len(user_input.split())
        short = int(words <= 8)
        casual = int(_is_casual_message(user_input))
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO communication_profile "
                "(id, message_count, total_words, short_message_count, casual_message_count) "
                "VALUES (1, 1, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET message_count = message_count + 1, "
                "total_words = total_words + excluded.total_words, "
                "short_message_count = short_message_count + excluded.short_message_count, "
                "casual_message_count = casual_message_count + excluded.casual_message_count",
                (words, short, casual),
            )
        return await self.get_communication_profile()

    async def get_communication_profile(self) -> CommunicationProfile:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT message_count, total_words, short_message_count, casual_message_count "
                "FROM communication_profile WHERE id = 1"
            ).fetchone()
        if row is None or row[0] < 3:
            return CommunicationProfile()
        messages, words, short_messages, casual_messages = row
        average_words = words / messages
        response_style = "concise" if average_words <= 12 or short_messages / messages >= 0.65 else "detailed" if average_words >= 28 else "balanced"
        tone = "casual" if casual_messages / messages >= 0.3 else "neutral"
        return CommunicationProfile(response_style=response_style, tone=tone)

    async def clear_communication_profile(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM communication_profile")

    async def get_voice_settings(self) -> VoiceSettings:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT enabled, engine, neural_voice, voice FROM voice_settings WHERE id = 1"
            ).fetchone()
        if row is None:
            return VoiceSettings()
        return VoiceSettings(
            enabled=bool(row[0]),
            engine=_normalize_engine(row[1]),
            neural_voice=_normalize_neural_voice(row[2]),
            voice=_normalize_voice(row[3]),
        )

    async def save_voice_settings(self, settings: VoiceSettings) -> None:
        if settings.voice not in _VOICE_IDS:
            raise ValueError("voice must be a supported voice profile")
        if settings.engine not in _VOICE_ENGINES:
            raise ValueError("engine must be a supported voice engine")
        if settings.neural_voice not in _NEURAL_VOICE_IDS:
            raise ValueError("neural_voice must be a supported neural voice profile")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO voice_settings (id, enabled, engine, neural_voice, voice) "
                "VALUES (1, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET enabled = excluded.enabled, "
                "engine = excluded.engine, neural_voice = excluded.neural_voice, "
                "voice = excluded.voice",
                (int(settings.enabled), settings.engine, settings.neural_voice, settings.voice),
            )


_VOICE_IDS = {
    "male_alex", "male_daniel", "male_eddy", "female_samantha", "female_ava", "female_karen"
}
_VOICE_ENGINES = {"neural", "system"}
_NEURAL_VOICE_IDS = {
    "male_ryan",
    "male_joe",
    "male_hfc",
    "female_amy",
    "female_hfc",
}


def _migrate_voice_settings(conn: sqlite3.Connection) -> None:
    """Add the v0.3 engine preference without discarding existing choices."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(voice_settings)")}
    if "engine" not in columns:
        conn.execute("ALTER TABLE voice_settings ADD COLUMN engine TEXT NOT NULL DEFAULT 'neural'")
    if "neural_voice" not in columns:
        conn.execute(
            "ALTER TABLE voice_settings ADD COLUMN neural_voice TEXT NOT NULL DEFAULT 'male_ryan'"
        )


def _normalize_voice(voice: str) -> str:
    """Migrate v0.1's gender-only setting without a database migration."""
    if voice == "male":
        return "male_alex"
    if voice == "female":
        return "female_samantha"
    return voice if voice in _VOICE_IDS else "male_alex"


def _normalize_engine(engine: str) -> str:
    return engine if engine in _VOICE_ENGINES else "neural"


def _normalize_neural_voice(voice: str) -> str:
    if voice == "female_lessac":
        return "female_amy"
    return voice if voice in _NEURAL_VOICE_IDS else "male_ryan"


def _is_casual_message(message: str) -> bool:
    normalized = message.casefold()
    markers = ("lol", "hey", "hi", "thanks", "pls", "gonna", "wanna", "im ", "i'm ")
    return any(marker in normalized for marker in markers)


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
