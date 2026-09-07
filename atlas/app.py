"""Native desktop interface for Atlas.

This module keeps the assistant local: it talks directly to the same core used
by the CLI and never starts a browser server.
"""
from __future__ import annotations

import asyncio
import logging
import math
import platform
import threading
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Protocol

from atlas.cli import _build_tool_registry, _configure_logging
from atlas.core.assistant.core import AssistantCore
from atlas.core.config.schema import AtlasConfig
from atlas.core.llm.ollama_provider import OllamaProvider
from atlas.core.memory.base import ActionRecord, SavedMemory, VoiceSettings
from atlas.core.memory.sqlite_store import SQLiteMemoryStore
from atlas.core.tools.registry import ConfirmationCallback
from atlas.core.voice.macos_speaker import VOICE_OPTIONS, _speech_text
from atlas.core.voice.piper_speaker import NEURAL_VOICE_OPTIONS, LocalVoiceSpeaker

_DEVICE_ASSET = Path(__file__).parent / "assets" / "atlas-device-core.png"
_STARTUP_ANNOUNCEMENT = "ATLAS — Adaptive Tactical Learning & Assistance System is now online."
_INITIAL_GREETING = "Hello — I’m Atlas. What would you like to work on?"

_MIDNIGHT = "#030817"
_DEEP_BLUE = "#071126"
_PANEL = "#0a1830"
_PANEL_ALT = "#0d2140"
_EDGE = "#1a4165"
_CYAN = "#6ee7f2"
_CYAN_DIM = "#2e96b2"
_TEXT = "#ecf8ff"
_MUTED = "#89a8c0"
_GOLD = "#ffc766"


class HandlesMessage(Protocol):
    async def handle_message(self, user_input: str) -> str: ...


class HandlesMemory(HandlesMessage, Protocol):
    async def list_saved_memories(self) -> list[SavedMemory]: ...

    async def clear_saved_memories(self) -> None: ...

    async def list_recent_actions(self) -> list[ActionRecord]: ...

    async def clear_action_history(self) -> None: ...

    async def get_voice_settings(self) -> VoiceSettings: ...

    async def save_voice_settings(self, settings: VoiceSettings) -> None: ...


class SpeaksResponses(Protocol):
    async def speak(
        self,
        text: str,
        settings: VoiceSettings,
        on_progress: Callable[[str], None] | None = None,
    ) -> bool: ...


async def _speak_startup_sequence(speaker: SpeaksResponses, settings: VoiceSettings) -> None:
    """Speak the online confirmation before Atlas's first visible reply."""
    for line in (_STARTUP_ANNOUNCEMENT, _INITIAL_GREETING):
        await speaker.speak(line, settings)


class DesktopConfirmationBridge:
    """Show a native approval dialog from Atlas's background request thread."""

    def __init__(self, root: tk.Tk) -> None:
        self._root = root

    async def confirm(self, tool_name: str, arguments: dict[str, object]) -> bool:
        loop = asyncio.get_running_loop()
        decision: asyncio.Future[bool] = loop.create_future()

        def ask() -> None:
            title, detail = self._describe(tool_name, arguments)
            approved = messagebox.askyesno(
                "Atlas confirmation", f"Atlas wants to {title}.\n\n{detail}\n\nAllow this action?", parent=self._root
            )
            loop.call_soon_threadsafe(decision.set_result, approved)

        self._root.after(0, ask)
        return await decision

    @staticmethod
    def _describe(tool_name: str, arguments: dict[str, object]) -> tuple[str, str]:
        if tool_name == "desktop.open_application":
            return "open an application", f"Application: {arguments.get('app', '')}"
        if tool_name == "desktop.open_file":
            return "open a local file", f"File: {arguments.get('path', '')}"
        if tool_name == "desktop.copy_to_clipboard":
            text = str(arguments.get("text", ""))
            preview = text if len(text) <= 300 else text[:297] + "..."
            return "copy text to your clipboard", f"Text: {preview}"
        if tool_name == "filesystem.create_text_file":
            text = str(arguments.get("text", ""))
            preview = text if len(text) <= 300 else text[:297] + "..."
            return "create a new text file", f"File: {arguments.get('path', '')}\nText: {preview}"
        if tool_name == "filesystem.create_folder":
            return "create a new folder", f"Folder: {arguments.get('path', '')}"
        if tool_name == "filesystem.copy_file":
            return (
                "copy a local file",
                f"From: {arguments.get('source', '')}\nTo: {arguments.get('destination', '')}",
            )
        if tool_name == "filesystem.move_file":
            return (
                "move a local file",
                f"From: {arguments.get('source', '')}\nTo: {arguments.get('destination', '')}",
            )
        if tool_name == "filesystem.rename_file":
            return (
                "rename a local file",
                f"File: {arguments.get('path', '')}\nNew name: {arguments.get('new_name', '')}",
            )
        if tool_name == "filesystem.move_to_trash":
            return "move a local file to Trash", f"File: {arguments.get('path', '')}"
        return "perform an action", f"Tool: {tool_name}"


class AtlasDesktopApp:
    def __init__(
        self,
        root: tk.Tk,
        assistant: HandlesMemory,
        name: str,
        voice_settings: VoiceSettings,
        neural_voice_models_dir: Path,
    ) -> None:
        self._root = root
        self._assistant = assistant
        self._name = name
        self._voice_settings = voice_settings
        self._speaker = LocalVoiceSpeaker(neural_voice_models_dir)
        self._spoken_rendered = ""
        self._busy = False
        self._field_state = "READY"
        self._thinking = False
        self._thinking_frame = 0
        self._core_phase = 0
        self._configure_window()
        self._build_interface()

    def _configure_window(self) -> None:
        self._root.title(f"{self._name} // Adaptive Command Deck")
        self._root.geometry("1280x800")
        self._root.minsize(900, 620)
        self._root.configure(bg=_MIDNIGHT)

    def _build_interface(self) -> None:
        sidebar = tk.Frame(self._root, bg=_DEEP_BLUE, width=292)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg=_DEEP_BLUE)
        brand.pack(anchor=tk.W, padx=26, pady=(28, 3))
        self._top_dot = tk.Label(brand, text="◉", fg=_CYAN, bg=_DEEP_BLUE, font=("Helvetica", 19, "bold"))
        self._top_dot.pack(side=tk.LEFT)
        tk.Label(brand, text="  ATLAS", fg=_TEXT, bg=_DEEP_BLUE, font=("Helvetica", 19, "bold")).pack(side=tk.LEFT)
        tk.Label(sidebar, text="ADAPTIVE COMMAND SYSTEM", fg=_CYAN, bg=_DEEP_BLUE, font=("Helvetica", 8, "bold")).pack(
            anchor=tk.W, padx=27
        )
        self._core_canvas = tk.Canvas(sidebar, height=238, bg=_DEEP_BLUE, highlightthickness=0, cursor="hand2")
        self._core_canvas.pack(fill=tk.X, padx=18, pady=(13, 8))
        self._core_canvas.bind("<Button-1>", lambda _: self._open_settings_window())
        tk.Label(sidebar, text="TAP CORE FOR VOICE SETTINGS", fg=_MUTED, bg=_DEEP_BLUE, font=("Helvetica", 8, "bold")).pack(
            anchor=tk.CENTER
        )
        tk.Frame(sidebar, height=1, bg=_EDGE).pack(fill=tk.X, padx=24, pady=(18, 18))
        tk.Label(sidebar, text="SYSTEM NAVIGATION", fg=_MUTED, bg=_DEEP_BLUE, font=("Helvetica", 8, "bold")).pack(
            anchor=tk.W, padx=27
        )
        self._navigation_button(sidebar, "◈  MEMORY ARCHIVE", self._open_memory_window).pack(
            fill=tk.X, padx=22, pady=(8, 0)
        )
        self._navigation_button(sidebar, "◫  ACTION LEDGER", self._open_action_history).pack(
            fill=tk.X, padx=22, pady=(7, 0)
        )
        self._navigation_button(sidebar, "◉  VOICE & SETTINGS", self._open_settings_window).pack(
            fill=tk.X, padx=22, pady=(7, 0)
        )
        field = tk.Frame(sidebar, bg=_PANEL, highlightbackground=_EDGE, highlightthickness=1)
        field.pack(side=tk.BOTTOM, fill=tk.X, padx=22, pady=23)
        tk.Label(field, text="LOCAL FIELD STATUS", fg=_CYAN, bg=_PANEL, font=("Helvetica", 8, "bold")).pack(anchor=tk.W, padx=14, pady=(13, 3))
        self._field_state_label = tk.Label(field, text="◈  READY", fg=_GOLD, bg=_PANEL, font=("Helvetica", 13, "bold"))
        self._field_state_label.pack(anchor=tk.W, padx=14)
        self._field_clock = tk.Label(field, text="", fg=_MUTED, bg=_PANEL, font=("Helvetica", 9))
        self._field_clock.pack(anchor=tk.W, padx=14, pady=(3, 1))
        tk.Label(field, text="18 TOOLS  ·  LOCAL MEMORY", fg="#527897", bg=_PANEL, font=("Helvetica", 8, "bold")).pack(anchor=tk.W, padx=14, pady=(0, 13))

        content = tk.Frame(self._root, bg=_MIDNIGHT)
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(2, 26), pady=22)
        topbar = tk.Frame(content, bg=_DEEP_BLUE, highlightbackground=_EDGE, highlightthickness=1)
        topbar.pack(fill=tk.X)
        heading = tk.Frame(topbar, bg=_DEEP_BLUE)
        heading.pack(side=tk.LEFT, padx=24, pady=17)
        tk.Label(heading, text="ATLAS // ADAPTIVE OPERATIONS", fg=_CYAN, bg=_DEEP_BLUE, font=("Helvetica", 9, "bold")).pack(anchor=tk.W)
        tk.Label(heading, text="What are we solving?", fg=_TEXT, bg=_DEEP_BLUE, font=("Helvetica", 24, "bold")).pack(anchor=tk.W, pady=(2, 0))
        self._session_clock = tk.Label(topbar, text="", fg=_MUTED, bg=_DEEP_BLUE, font=("Helvetica", 9, "bold"))
        self._session_clock.pack(side=tk.RIGHT, padx=22)
        status_row = tk.Frame(content, bg=_MIDNIGHT)
        status_row.pack(fill=tk.X, pady=(10, 10))
        self._mode_indicator = self._status_chip(status_row, "●  LOCAL CORE ONLINE", _CYAN)
        self._mode_indicator.pack(side=tk.LEFT)
        self._status_chip(status_row, "◈  PRIVATE SESSION", _GOLD).pack(side=tk.LEFT, padx=8)
        self._ghost_button(status_row, "VOICE SETTINGS", self._open_settings_window).pack(side=tk.RIGHT)
        self._ghost_button(status_row, "MEMORY", self._open_memory_window).pack(side=tk.RIGHT, padx=(0, 8))

        transcript_shell = tk.Frame(content, bg=_PANEL, highlightbackground=_EDGE, highlightthickness=1)
        transcript_shell.pack(fill=tk.BOTH, expand=True)
        transcript_header = tk.Frame(transcript_shell, bg=_PANEL_ALT)
        transcript_header.pack(fill=tk.X)
        tk.Label(transcript_header, text="CONVERSATION STREAM", fg=_CYAN, bg=_PANEL_ALT, font=("Helvetica", 9, "bold")).pack(side=tk.LEFT, padx=17, pady=10)
        tk.Label(transcript_header, text="LIVE LOCAL INFERENCE", fg=_MUTED, bg=_PANEL_ALT, font=("Helvetica", 8, "bold")).pack(side=tk.RIGHT, padx=17)
        self._transcript = scrolledtext.ScrolledText(transcript_shell, wrap=tk.WORD, state=tk.DISABLED, bg=_PANEL, fg=_TEXT, insertbackground=_CYAN, relief=tk.FLAT, padx=26, pady=22, font=("Helvetica", 12), highlightthickness=0)
        self._transcript.pack(fill=tk.BOTH, expand=True)
        self._transcript.tag_configure("atlas", foreground=_CYAN, font=("Helvetica", 10, "bold"))
        self._transcript.tag_configure("user", foreground=_GOLD, font=("Helvetica", 10, "bold"))
        self._append("Atlas", _INITIAL_GREETING)

        composer = tk.Frame(content, bg=_DEEP_BLUE, highlightbackground=_EDGE, highlightthickness=1)
        composer.pack(fill=tk.X, pady=(10, 0))
        composer_head = tk.Frame(composer, bg=_DEEP_BLUE)
        composer_head.pack(fill=tk.X, padx=16, pady=(12, 0))
        tk.Label(composer_head, text="COMMAND INPUT", fg=_CYAN, bg=_DEEP_BLUE, font=("Helvetica", 8, "bold")).pack(side=tk.LEFT)
        self._input_status = tk.Label(composer_head, text="ENTER TO TRANSMIT", fg=_MUTED, bg=_DEEP_BLUE, font=("Helvetica", 8, "bold"))
        self._input_status.pack(side=tk.RIGHT)
        input_shell = tk.Frame(composer, bg="#020712", highlightbackground="#1f5878", highlightthickness=1)
        input_shell.pack(fill=tk.X, padx=16, pady=(7, 15))
        self._input = tk.Text(input_shell, height=3, wrap=tk.WORD, bg="#020712", fg=_TEXT, insertbackground=_CYAN, relief=tk.FLAT, padx=14, pady=11, font=("Helvetica", 12), highlightthickness=0)
        self._input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._input.bind("<Return>", self._send_event)
        self._input.bind("<Command-Return>", self._send_event)
        self._input.bind("<Control-Return>", self._send_event)
        self._input.bind("<KeyRelease>", self._update_input_status)
        self._send_button = tk.Button(input_shell, text="EXECUTE  ›", command=self._send, bg=_CYAN, fg="#031019", activebackground="#b5fbff", activeforeground="#031019", relief=tk.FLAT, bd=0, font=("Helvetica", 10, "bold"), padx=22, pady=12, cursor="hand2")
        self._send_button.pack(side=tk.RIGHT, padx=10, pady=10)
        self._input.focus_set()
        self._refresh_field()
        self._animate_core()
        if self._voice_settings.enabled:
            self._root.after(350, self._start_startup_voice)

    @staticmethod
    def _navigation_button(parent: tk.Misc, text: str, command: Callable[[], None]) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            anchor=tk.W,
            bg=_DEEP_BLUE,
            fg=_TEXT,
            activebackground=_PANEL_ALT,
            activeforeground=_CYAN,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground="#173c5a",
            highlightcolor=_CYAN,
            font=("Helvetica", 10, "bold"),
            padx=15,
            pady=11,
            cursor="hand2",
        )

    @staticmethod
    def _ghost_button(parent: tk.Misc, text: str, command: Callable[[], None]) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=_MIDNIGHT,
            fg=_TEXT,
            activebackground=_PANEL_ALT,
            activeforeground=_CYAN,
            relief=tk.FLAT,
            bd=0,
            highlightthickness=1,
            highlightbackground="#214c6a",
            highlightcolor=_CYAN,
            font=("Helvetica", 9, "bold"),
            padx=12,
            pady=7,
            cursor="hand2",
        )

    @staticmethod
    def _status_chip(parent: tk.Misc, text: str, color: str) -> tk.Label:
        return tk.Label(parent, text=text, fg=color, bg=_PANEL_ALT, font=("Helvetica", 8, "bold"), padx=12, pady=7)

    def _animate_core(self) -> None:
        """Render a lightweight animated command core without external media."""
        if not self._core_canvas.winfo_exists():
            return
        canvas = self._core_canvas
        width = max(canvas.winfo_width(), 250)
        height = max(canvas.winfo_height(), 238)
        center_x, center_y = width / 2, height / 2
        canvas.delete("all")
        for x in range(0, width + 1, 24):
            canvas.create_line(x, 0, x, height, fill="#091a32")
        for y in range(0, height + 1, 24):
            canvas.create_line(0, y, width, y, fill="#091a32")
        for radius, color, width_line in ((76, "#123a5a", 1), (57, "#1a5775", 2), (34, _CYAN_DIM, 2)):
            canvas.create_oval(center_x - radius, center_y - radius, center_x + radius, center_y + radius, outline=color, width=width_line)
        for offset, color in ((0, _CYAN), (135, "#4c8eb7"), (245, _GOLD)):
            start = (self._core_phase + offset) % 360
            radius = 76 if offset == 0 else 57
            canvas.create_arc(center_x - radius, center_y - radius, center_x + radius, center_y + radius, start=start, extent=68, style=tk.ARC, outline=color, width=3)
        pulse = 10 + 3 * math.sin(self._core_phase / 12)
        canvas.create_oval(center_x - pulse, center_y - pulse, center_x + pulse, center_y + pulse, fill=_CYAN, outline="")
        canvas.create_oval(center_x - 4, center_y - 4, center_x + 4, center_y + 4, fill="#e7ffff", outline="")
        for angle in range(0, 360, 45):
            radians = math.radians(angle + self._core_phase / 5)
            particle_x = center_x + math.cos(radians) * 96
            particle_y = center_y + math.sin(radians) * 96
            canvas.create_oval(particle_x - 2, particle_y - 2, particle_x + 2, particle_y + 2, fill="#3f88aa", outline="")
        canvas.create_text(center_x, center_y + 116, text="ADAPTIVE TACTICAL CORE", fill=_MUTED, font=("Helvetica", 8, "bold"))
        self._core_phase = (self._core_phase + 6) % 360
        self._root.after(80, self._animate_core)

    def _start_startup_voice(self) -> None:
        threading.Thread(target=self._speak_startup_voice, daemon=True).start()

    def _speak_startup_voice(self) -> None:
        asyncio.run(_speak_startup_sequence(self._speaker, self._voice_settings))

    def _refresh_field(self) -> None:
        now = datetime.now().astimezone().strftime("LOCAL TIME  %H:%M:%S  %Z")
        self._field_clock.configure(text=now)
        self._session_clock.configure(text=now)
        self._root.after(1_000, self._refresh_field)

    def _update_input_status(self, _: tk.Event[tk.Misc] | None = None) -> None:
        characters = len(self._input.get("1.0", "end-1c"))
        self._input_status.configure(
            text="ENTER TO TRANSMIT" if characters == 0 else f"SIGNAL BUFFER  ·  {characters} CHARS"
        )

    def _open_memory_window(self) -> None:
        window = tk.Toplevel(self._root)
        window.title("Atlas // Saved Memories")
        window.geometry("520x410")
        window.configure(bg="#0b121c")
        tk.Label(window, text="SAVED MEMORIES", fg="#73e0d4", bg="#0b121c", font=("Helvetica", 16, "bold")).pack(anchor=tk.W, padx=22, pady=(22, 2))
        tk.Label(window, text="Only facts you explicitly asked Atlas to remember are listed here.", fg="#91a6b8", bg="#0b121c", font=("Helvetica", 10)).pack(anchor=tk.W, padx=22, pady=(0, 15))
        contents = scrolledtext.ScrolledText(window, wrap=tk.WORD, state=tk.DISABLED, bg="#101a26", fg="#e8f4fb", relief=tk.FLAT, padx=14, pady=12, font=("Helvetica", 11))
        contents.pack(fill=tk.BOTH, expand=True, padx=22)

        def refresh() -> None:
            threading.Thread(target=load, daemon=True).start()

        def load() -> None:
            memories = asyncio.run(self._assistant.list_saved_memories())
            self._root.after(0, render, memories)

        def render(memories: list[SavedMemory]) -> None:
            contents.configure(state=tk.NORMAL)
            contents.delete("1.0", tk.END)
            contents.insert(tk.END, "\n".join(f"• {memory.content}" for memory in memories) or "No saved memories yet.")
            contents.configure(state=tk.DISABLED)

        def clear_all() -> None:
            if messagebox.askyesno("Clear saved memories", "Remove all saved memories? This cannot be undone.", parent=window):
                threading.Thread(target=clear, daemon=True).start()

        def clear() -> None:
            asyncio.run(self._assistant.clear_saved_memories())
            self._root.after(0, refresh)

        tk.Button(window, text="CLEAR ALL MEMORIES", command=clear_all, bg="#2e1724", fg="#ffd5da", activebackground="#572638", activeforeground="#ffffff", relief=tk.FLAT, bd=0, highlightthickness=1, highlightbackground="#74384b", font=("Helvetica", 9, "bold"), padx=14, pady=9, cursor="hand2").pack(anchor=tk.E, padx=22, pady=18)
        refresh()

    def _open_action_history(self) -> None:
        window = tk.Toplevel(self._root)
        window.title("Atlas // Action History")
        window.geometry("620x440")
        window.configure(bg="#0b121c")
        tk.Label(window, text="ACTION HISTORY", fg="#73e0d4", bg="#0b121c", font=("Helvetica", 16, "bold")).pack(anchor=tk.W, padx=22, pady=(22, 2))
        tk.Label(window, text="Local record of confirmation-gated actions. Clipboard contents are never recorded.", fg="#91a6b8", bg="#0b121c", font=("Helvetica", 10)).pack(anchor=tk.W, padx=22, pady=(0, 15))
        contents = scrolledtext.ScrolledText(window, wrap=tk.WORD, state=tk.DISABLED, bg="#101a26", fg="#e8f4fb", relief=tk.FLAT, padx=14, pady=12, font=("Helvetica", 11))
        contents.pack(fill=tk.BOTH, expand=True, padx=22)

        def refresh() -> None:
            threading.Thread(target=load, daemon=True).start()

        def load() -> None:
            actions = asyncio.run(self._assistant.list_recent_actions())
            self._root.after(0, render, actions)

        def render(actions: list[ActionRecord]) -> None:
            contents.configure(state=tk.NORMAL)
            contents.delete("1.0", tk.END)
            lines = [
                f"[{action.outcome}] {datetime.fromtimestamp(action.timestamp).astimezone().strftime('%b %d, %H:%M')}\n{action.summary}"
                for action in actions
            ]
            contents.insert(tk.END, "\n\n".join(lines) or "No confirmed actions yet.")
            contents.configure(state=tk.DISABLED)

        def clear_all() -> None:
            if messagebox.askyesno("Clear action history", "Remove all action history?", parent=window):
                threading.Thread(target=clear, daemon=True).start()

        def clear() -> None:
            asyncio.run(self._assistant.clear_action_history())
            self._root.after(0, refresh)

        tk.Button(window, text="CLEAR ACTION HISTORY", command=clear_all, bg="#2e1724", fg="#ffd5da", activebackground="#572638", activeforeground="#ffffff", relief=tk.FLAT, bd=0, highlightthickness=1, highlightbackground="#74384b", font=("Helvetica", 9, "bold"), padx=14, pady=9, cursor="hand2").pack(anchor=tk.E, padx=22, pady=18)
        refresh()

    def _open_settings_window(self) -> None:
        window = tk.Toplevel(self._root)
        window.title("Atlas // Settings")
        window.geometry("620x735")
        window.configure(bg="#0b121c")
        tk.Label(window, text="⚙  SETTINGS", fg="#73e0d4", bg="#0b121c", font=("Helvetica", 16, "bold")).pack(anchor=tk.W, padx=22, pady=(22, 2))
        tk.Label(window, text="Configure how Atlas sounds and responds on this Mac.", fg="#91a6b8", bg="#0b121c", font=("Helvetica", 10)).pack(anchor=tk.W, padx=22, pady=(0, 14))
        tabs = ttk.Notebook(window)
        tabs.pack(fill=tk.BOTH, expand=True, padx=22)
        voice_tab = tk.Frame(tabs, bg="#101a26")
        tabs.add(voice_tab, text="  ◉  VOICE  ")
        voice_enabled = tk.BooleanVar(value=self._voice_settings.enabled)
        voice_engine = tk.StringVar(value=self._voice_settings.engine)
        neural_voice = tk.StringVar(value=self._voice_settings.neural_voice)
        voice_type = tk.StringVar(value=self._voice_settings.voice)
        tk.Checkbutton(voice_tab, text="READ ATLAS RESPONSES ALOUD", variable=voice_enabled, bg="#101a26", fg="#e8f4fb", selectcolor="#101a26", activebackground="#101a26", activeforeground="#e8f4fb", font=("Helvetica", 10, "bold")).pack(anchor=tk.W, padx=16, pady=(16, 10))
        tk.Label(voice_tab, text="VOICE ENGINE", fg="#73e0d4", bg="#101a26", font=("Helvetica", 9, "bold")).pack(anchor=tk.W, padx=16)
        tk.Radiobutton(voice_tab, text="LOCAL NEURAL  ·  Piper voice model (recommended)", variable=voice_engine, value="neural", bg="#101a26", fg="#e8f4fb", selectcolor="#101a26", activebackground="#101a26", activeforeground="#e8f4fb", font=("Helvetica", 10, "bold")).pack(anchor=tk.W, padx=16, pady=(3, 0))
        tk.Label(voice_tab, text="More natural speech, synthesized and played entirely on this Mac.", fg="#91a6b8", bg="#101a26", font=("Helvetica", 9)).pack(anchor=tk.W, padx=38)
        tk.Radiobutton(voice_tab, text="MACOS SYSTEM  ·  Built-in voice fallback", variable=voice_engine, value="system", bg="#101a26", fg="#e8f4fb", selectcolor="#101a26", activebackground="#101a26", activeforeground="#e8f4fb", font=("Helvetica", 10, "bold")).pack(anchor=tk.W, padx=16, pady=(6, 0))
        tk.Label(voice_tab, text="Used automatically if the neural voice is not installed yet.", fg="#91a6b8", bg="#101a26", font=("Helvetica", 9)).pack(anchor=tk.W, padx=38)
        neural_status = tk.Label(
            voice_tab, fg="#f6c35c", bg="#101a26", font=("Helvetica", 9, "bold")
        )
        neural_status.pack(anchor=tk.W, padx=16, pady=(8, 0))
        tk.Label(voice_tab, text="NEURAL VOICE PROFILE", fg="#73e0d4", bg="#101a26", font=("Helvetica", 9, "bold")).pack(anchor=tk.W, padx=16, pady=(8, 0))
        for voice_id, (name, description, _) in NEURAL_VOICE_OPTIONS.items():
            tk.Radiobutton(voice_tab, text=f"{name}  ·  {description}", variable=neural_voice, value=voice_id, bg="#101a26", fg="#e8f4fb", selectcolor="#101a26", activebackground="#101a26", activeforeground="#e8f4fb", font=("Helvetica", 10)).pack(anchor=tk.W, padx=16, pady=1)
        tk.Label(voice_tab, text="MACOS FALLBACK PROFILE", fg="#73e0d4", bg="#101a26", font=("Helvetica", 9, "bold")).pack(anchor=tk.W, padx=16, pady=(8, 0))
        for voice_id, (name, description, _, _) in VOICE_OPTIONS.items():
            tk.Radiobutton(voice_tab, text=f"{name}  ·  {description}", variable=voice_type, value=voice_id, bg="#101a26", fg="#e8f4fb", selectcolor="#101a26", activebackground="#101a26", activeforeground="#e8f4fb", font=("Helvetica", 10)).pack(anchor=tk.W, padx=16, pady=2)

        def refresh_neural_status(*_: str) -> None:
            if self._speaker.is_neural_voice_ready(neural_voice.get()):
                neural_status.configure(text="Selected neural model installed and ready.", fg="#73e0d4")
            else:
                neural_status.configure(
                    text="Selected neural model not installed — Atlas will use the macOS fallback.",
                    fg="#f6c35c",
                )

        neural_voice.trace_add("write", refresh_neural_status)
        refresh_neural_status()

        def selected_settings() -> VoiceSettings:
            return VoiceSettings(
                enabled=voice_enabled.get(),
                engine=voice_engine.get(),
                neural_voice=neural_voice.get(),
                voice=voice_type.get(),
            )

        def test_voice() -> None:
            threading.Thread(
                target=lambda: asyncio.run(
                    self._speaker.speak("Voice interface online. How can I help?", selected_settings())
                ),
                daemon=True,
            ).start()

        def save() -> None:
            selected = selected_settings()
            self._voice_settings = selected
            threading.Thread(
                target=lambda: asyncio.run(self._assistant.save_voice_settings(selected)), daemon=True
            ).start()
            window.destroy()

        buttons = tk.Frame(window, bg="#0b121c")
        buttons.pack(fill=tk.X, padx=22, pady=22)
        tk.Button(buttons, text="TEST VOICE", command=test_voice, bg=_PANEL_ALT, fg=_TEXT, activebackground="#1b4e70", activeforeground=_CYAN, relief=tk.FLAT, bd=0, highlightthickness=1, highlightbackground="#245676", font=("Helvetica", 9, "bold"), padx=14, pady=9, cursor="hand2").pack(side=tk.LEFT)
        tk.Button(buttons, text="SAVE SETTINGS", command=save, bg=_CYAN, fg="#031019", activebackground="#b5fbff", activeforeground="#031019", relief=tk.FLAT, bd=0, font=("Helvetica", 9, "bold"), padx=14, pady=9, cursor="hand2").pack(side=tk.RIGHT)

    def _set_field_state(self, state: str) -> None:
        self._field_state = state
        colors = {"READY": _GOLD, "PROCESSING": _CYAN}
        marker = "◈" if state == "READY" else "◌"
        self._field_state_label.configure(text=f"{marker}  {state}", fg=colors[state])
        mode_text = "●  LOCAL CORE ONLINE" if state == "READY" else "◌  ANALYZING REQUEST"
        self._mode_indicator.configure(text=mode_text, fg=colors[state])
        self._thinking = state == "PROCESSING"
        if self._thinking:
            self._animate_top_dot()
        else:
            self._top_dot.configure(text="◉", fg=_CYAN)

    def _animate_top_dot(self) -> None:
        if not self._thinking:
            return
        frames = ("◔", "◑", "◕", "◒")
        self._top_dot.configure(text=frames[self._thinking_frame % len(frames)], fg=_GOLD)
        self._thinking_frame += 1
        self._root.after(120, self._animate_top_dot)

    def _append(self, speaker: str, message: str) -> None:
        self._transcript.configure(state=tk.NORMAL)
        tag = "atlas" if speaker == self._name else "user"
        self._transcript.insert(tk.END, f"{speaker.upper()}\n", tag)
        self._transcript.insert(tk.END, f"{message}\n\n")
        self._transcript.configure(state=tk.DISABLED)
        self._transcript.see(tk.END)

    def _send_event(self, event: tk.Event[tk.Misc]) -> str:
        self._send()
        return "break"

    def _send(self) -> None:
        if self._busy:
            return
        message = self._input.get("1.0", tk.END).strip()
        if not message:
            return
        self._input.delete("1.0", tk.END)
        self._update_input_status()
        self._append("You", message)
        self._busy = True
        self._set_field_state("PROCESSING")
        self._send_button.configure(state=tk.DISABLED, text="ANALYZING…")
        threading.Thread(target=self._reply, args=(message,), daemon=True).start()

    def _reply(self, message: str) -> None:
        try:
            reply = asyncio.run(self._assistant.handle_message(message))
        except Exception:
            logging.getLogger("atlas.app").exception("desktop chat request failed")
            reply = "I’m unable to complete that request right now."
        self._root.after(0, self._finish_reply, reply)

    def _finish_reply(self, reply: str) -> None:
        if self._voice_settings.enabled:
            spoken_reply = _speech_text(reply)
            self._begin_spoken_reply()
            threading.Thread(target=self._speak_reply, args=(spoken_reply,), daemon=True).start()
        else:
            self._append(self._name, reply)
        self._busy = False
        self._set_field_state("READY")
        self._send_button.configure(state=tk.NORMAL, text="EXECUTE  ›")
        self._input.focus_set()

    def _begin_spoken_reply(self) -> None:
        self._spoken_rendered = ""
        self._transcript.configure(state=tk.NORMAL)
        self._transcript.insert(tk.END, f"{self._name.upper()}\n", "atlas")
        self._transcript.configure(state=tk.DISABLED)
        self._transcript.see(tk.END)

    def _append_spoken_fragment(self, fragment: str) -> None:
        self._spoken_rendered += fragment
        self._transcript.configure(state=tk.NORMAL)
        self._transcript.insert(tk.END, fragment)
        self._transcript.configure(state=tk.DISABLED)
        self._transcript.see(tk.END)

    def _complete_spoken_reply(self, reply: str) -> None:
        remaining = reply[len(self._spoken_rendered):]
        self._transcript.configure(state=tk.NORMAL)
        self._transcript.insert(tk.END, remaining + "\n\n")
        self._transcript.configure(state=tk.DISABLED)
        self._transcript.see(tk.END)

    def _speak_reply(self, reply: str) -> None:
        def progress(fragment: str) -> None:
            self._root.after(0, self._append_spoken_fragment, fragment)

        asyncio.run(self._speaker.speak(reply, self._voice_settings, progress))
        self._root.after(0, self._complete_spoken_reply, reply)


async def _create_assistant(
    config: AtlasConfig, *, confirm: ConfirmationCallback | None = None
) -> AssistantCore:
    llm = OllamaProvider(host=config.ollama_host, model=config.llm_model, temperature=config.llm_temperature, timeout=config.llm_request_timeout_seconds, context_tokens=config.llm_context_tokens, max_response_tokens=config.llm_max_response_tokens, keep_alive=config.llm_keep_alive)
    if not await llm.is_available():
        raise RuntimeError(f"Could not reach Ollama at {config.ollama_host}.")
    memory = SQLiteMemoryStore(config.memory_db_path)
    return AssistantCore(assistant_name=config.assistant_name, llm=llm, memory=memory, tools=_build_tool_registry(confirm=confirm, audit=memory.record_action), max_history_turns=config.memory_max_turns, max_history_characters=config.memory_max_context_characters)


class ConnectionScreen:
    """Animated local-core boot screen that stays responsive during the Ollama check."""

    def __init__(self, root: tk.Tk, config: AtlasConfig) -> None:
        self._root = root
        self._config = config
        self._confirmation = DesktopConfirmationBridge(root)
        self._window = tk.Toplevel(root)
        self._window.overrideredirect(True)
        self._window.configure(bg=_MIDNIGHT)
        self._window.geometry("600x430")
        self._window.update_idletasks()
        x = (self._window.winfo_screenwidth() - 600) // 2
        y = (self._window.winfo_screenheight() - 430) // 2
        self._window.geometry(f"600x430+{x}+{y}")
        self._phase = 0
        self._build()

    def _build(self) -> None:
        frame = tk.Frame(self._window, bg=_MIDNIGHT, highlightbackground=_EDGE, highlightthickness=1)
        frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        tk.Label(frame, text="ATLAS // INITIALIZING", fg=_CYAN, bg=_MIDNIGHT, font=("Helvetica", 9, "bold")).pack(anchor=tk.W, padx=28, pady=(24, 0))
        self._radar = tk.Canvas(frame, height=195, bg=_MIDNIGHT, highlightthickness=0)
        self._radar.pack(fill=tk.X, pady=(3, 0))
        tk.Label(frame, text="ADAPTIVE TACTICAL CORE", fg=_TEXT, bg=_MIDNIGHT, font=("Helvetica", 23, "bold")).pack()
        tk.Label(frame, text="LOCAL INFERENCE LINK", fg=_MUTED, bg=_MIDNIGHT, font=("Helvetica", 9, "bold")).pack(pady=(3, 14))
        self._status = tk.Label(frame, text="Checking local inference connection…", fg=_TEXT, bg=_MIDNIGHT, font=("Helvetica", 12, "bold"))
        self._status.pack()
        self._detail = tk.Label(frame, text="OLLAMA  ·  macOS  ·  PRIVATE SESSION", fg=_MUTED, bg=_MIDNIGHT, font=("Helvetica", 9, "bold"))
        self._detail.pack(pady=(5, 0))
        self._retry = tk.Button(frame, text="RETRY CONNECTION", command=self.start_check, bg=_CYAN, fg="#031019", activebackground="#b5fbff", relief=tk.FLAT, bd=0, font=("Helvetica", 9, "bold"), padx=14, pady=8, cursor="hand2")
        self._animate()
        self.start_check()

    def _animate(self) -> None:
        if not self._window.winfo_exists():
            return
        self._radar.delete("all")
        width = max(self._radar.winfo_width(), 600)
        center_x, center_y = width / 2, 96
        for x in range(0, width + 1, 30):
            self._radar.create_line(x, 0, x, 195, fill="#081a31")
        for y in range(0, 196, 30):
            self._radar.create_line(0, y, width, y, fill="#081a31")
        for radius, color, line_width in ((78, "#123a5a", 1), (58, "#1c607c", 2), (34, _CYAN_DIM, 2)):
            self._radar.create_oval(center_x - radius, center_y - radius, center_x + radius, center_y + radius, outline=color, width=line_width)
        for offset, color in ((0, _CYAN), (120, "#568caf"), (240, _GOLD)):
            radius = 78 if offset == 0 else 58
            self._radar.create_arc(center_x - radius, center_y - radius, center_x + radius, center_y + radius, start=(self._phase + offset) % 360, extent=74, style=tk.ARC, outline=color, width=3)
        pulse = 9 + 3 * math.sin(self._phase / 12)
        self._radar.create_oval(center_x - pulse, center_y - pulse, center_x + pulse, center_y + pulse, fill=_CYAN, outline="")
        self._radar.create_text(center_x, center_y + 116, text="ESTABLISHING LOCAL LINK", fill=_MUTED, font=("Helvetica", 8, "bold"))
        self._phase += 8
        self._window.after(80, self._animate)

    def start_check(self) -> None:
        self._retry.pack_forget()
        self._status.configure(text="Checking local inference connection…", fg=_TEXT)
        self._detail.configure(text=f"OLLAMA  ·  {platform.system().upper()}  ·  PRIVATE SESSION")
        threading.Thread(target=self._connect, daemon=True).start()

    def _connect(self) -> None:
        try:
            assistant = asyncio.run(_create_assistant(self._config, confirm=self._confirmation.confirm))
            voice_settings = asyncio.run(assistant.get_voice_settings())
        except RuntimeError as exc:
            self._root.after(0, self._failed, str(exc))
            return
        self._root.after(0, self._ready, assistant, voice_settings)

    def _ready(self, assistant: AssistantCore, voice_settings: VoiceSettings) -> None:
        self._status.configure(text="Local core verified", fg=_CYAN)
        self._detail.configure(text="OLLAMA ONLINE  ·  LAUNCHING COMMAND DECK")
        self._window.after(650, lambda: self._launch(assistant, voice_settings))

    def _failed(self, error: str) -> None:
        self._status.configure(text="Connection unavailable", fg=_GOLD)
        self._detail.configure(text=error)
        self._retry.pack(pady=(16, 0))

    def _launch(self, assistant: AssistantCore, voice_settings: VoiceSettings) -> None:
        self._window.destroy()
        self._root.deiconify()
        AtlasDesktopApp(
            self._root,
            assistant,
            self._config.assistant_name,
            voice_settings,
            self._config.neural_voice_models_dir,
        )


def main() -> None:
    config = AtlasConfig()
    config.ensure_directories()
    _configure_logging(config)
    root = tk.Tk()
    root.withdraw()
    ConnectionScreen(root, config)
    root.mainloop()


if __name__ == "__main__":
    main()
