"""Native desktop interface for Atlas.

This module keeps the assistant local: it talks directly to the same core used
by the CLI and never starts a browser server.
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import threading
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Any, Literal, Protocol

from atlas.cli import _build_tool_registry, _configure_logging
from atlas.core.assistant.core import AssistantCore
from atlas.core.config.schema import AtlasConfig
from atlas.core.llm.ollama_provider import OllamaProvider
from atlas.core.memory.base import ActionRecord, SavedMemory, VoiceSettings
from atlas.core.memory.sqlite_store import SQLiteMemoryStore
from atlas.core.tools.registry import ConfirmationCallback
from atlas.core.voice.macos_speaker import VOICE_OPTIONS, _speech_text
from atlas.core.voice.piper_speaker import NEURAL_VOICE_OPTIONS, LocalVoiceSpeaker
from atlas.core.voice.whisper_input import (
    PushToTalkRecorder,
    VoiceInputError,
    WhisperCppRecognizer,
    is_ambiguous_voice_transcript,
    normalize_voice_transcript,
)

_DEVICE_ASSET = Path(__file__).parent / "assets" / "atlas-device-core.png"
_STARTUP_ANNOUNCEMENT = "ATLAS — Adaptive Tactical Learning & Assistance System is now online."

# Atlas's visual language comes from celestial charts and old navigation tools:
# blue chart paper, copper bearings, and a cool signal light—not generic sci-fi
# black or a single neon accent.
_NIGHT_CHART = "#10233D"
_MERIDIAN = "#1D4E70"
_OBSERVATORY = "#24445E"
_STAR_PAPER = "#E3E7DE"
_COPPER_BEARING = "#C78958"
_SIGNAL_TEAL = "#6DCBC8"
_SKY_MIST = "#B7CBD1"
_QUIET_BLUE = "#17314A"
_FOCUS_RING = "#E7C27A"

_TYPEFACE = "Avenir Next"


class HandlesMessage(Protocol):
    async def handle_message(self, user_input: str) -> str: ...


class HandlesMemory(HandlesMessage, Protocol):
    async def list_saved_memories(self) -> list[SavedMemory]: ...

    async def clear_saved_memories(self) -> None: ...

    async def list_recent_actions(self) -> list[ActionRecord]: ...

    async def clear_action_history(self) -> None: ...

    async def clear_communication_profile(self) -> None: ...

    async def suggestions_for(self, user_input: str, reply: str) -> list[str]: ...

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
    """Speak the online confirmation without adding a repetitive chat greeting."""
    await speaker.speak(_STARTUP_ANNOUNCEMENT, settings)


async def _play_system_sound(name: str) -> None:
    """Play an immediate macOS listening chime; it never uses the language model."""
    if platform.system() != "Darwin":
        return
    sound = Path("/System/Library/Sounds") / f"{name}.aiff"
    if not sound.is_file():
        return
    process = await asyncio.create_subprocess_exec(
        "afplay", str(sound), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    await process.wait()


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
        voice_input_models_dir: Path,
    ) -> None:
        self._root = root
        self._assistant = assistant
        self._name = name
        self._voice_settings = voice_settings
        self._speaker = LocalVoiceSpeaker(neural_voice_models_dir)
        self._voice_input = PushToTalkRecorder(WhisperCppRecognizer(voice_input_models_dir))
        self._recording = False
        self._voice_ack_token = 0
        self._spoken_rendered = ""
        self._busy = False
        self._field_state = "Ready"
        self._prefers_reduced_motion = os.environ.get("ATLAS_REDUCED_MOTION", "").casefold() in {
            "1",
            "true",
            "yes",
        }
        self._core_phase = 0
        self._configure_window()
        self._build_interface()
        self._root.protocol("WM_DELETE_WINDOW", self._root.destroy)

    def _configure_window(self) -> None:
        self._root.title(self._name)
        self._root.geometry("1240x790")
        self._root.minsize(760, 560)
        self._root.configure(bg=_NIGHT_CHART)
        self._root.bind("<Configure>", self._reflow_for_width)

    def _build_interface(self) -> None:
        self._sidebar = tk.Frame(self._root, bg=_QUIET_BLUE, width=244)
        self._sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self._sidebar.pack_propagate(False)
        brand = tk.Frame(self._sidebar, bg=_QUIET_BLUE)
        brand.pack(anchor=tk.W, padx=28, pady=(34, 2))
        tk.Label(brand, text="Atlas", fg=_STAR_PAPER, bg=_QUIET_BLUE, font=(_TYPEFACE, 25, "bold")).pack(anchor=tk.W)
        self._brand_subtitle = tk.Label(
            brand,
            text="Your private local assistant",
            fg=_SKY_MIST,
            bg=_QUIET_BLUE,
            font=(_TYPEFACE, 11),
        )
        self._brand_subtitle.pack(anchor=tk.W, pady=(2, 0))
        self._core_canvas = tk.Canvas(
            self._sidebar,
            height=178,
            bg=_QUIET_BLUE,
            highlightthickness=0,
            cursor="hand2",
            takefocus=True,
        )
        self._core_canvas.pack(fill=tk.X, padx=24, pady=(17, 0))
        self._core_canvas.bind("<Button-1>", lambda _: self._open_settings_window())
        self._core_canvas.bind("<Return>", lambda _: self._open_settings_window())
        tk.Label(self._sidebar, text="Voice settings", fg=_SKY_MIST, bg=_QUIET_BLUE, font=(_TYPEFACE, 11)).pack(
            anchor=tk.CENTER, pady=(0, 20)
        )
        nav = tk.Frame(self._sidebar, bg=_QUIET_BLUE)
        nav.pack(fill=tk.X, padx=18)
        self._navigation_button(nav, "Memory", self._open_memory_window).pack(fill=tk.X, pady=(0, 5))
        self._navigation_button(nav, "Action history", self._open_action_history).pack(fill=tk.X, pady=5)
        self._navigation_button(nav, "Settings", self._open_settings_window).pack(fill=tk.X, pady=5)
        field = tk.Frame(self._sidebar, bg=_QUIET_BLUE)
        field.pack(side=tk.BOTTOM, fill=tk.X, padx=28, pady=28)
        tk.Frame(field, height=2, bg=_MERIDIAN).pack(fill=tk.X, pady=(0, 12))
        self._field_state_label = tk.Label(
            field, text="Local and ready", fg=_SIGNAL_TEAL, bg=_QUIET_BLUE, font=(_TYPEFACE, 14, "bold")
        )
        self._field_state_label.pack(anchor=tk.W)
        self._field_clock = tk.Label(field, text="", fg=_SKY_MIST, bg=_QUIET_BLUE, font=(_TYPEFACE, 10))
        self._field_clock.pack(anchor=tk.W, pady=(4, 0))
        tk.Label(
            field,
            text="Private session. Microphone off until pressed.",
            fg=_SKY_MIST,
            bg=_QUIET_BLUE,
            font=(_TYPEFACE, 10),
            wraplength=184,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(10, 0))

        content = tk.Frame(self._root, bg=_NIGHT_CHART)
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(42, 42), pady=(34, 28))
        topbar = tk.Frame(content, bg=_NIGHT_CHART)
        topbar.pack(fill=tk.X)
        heading = tk.Frame(topbar, bg=_NIGHT_CHART)
        heading.pack(side=tk.LEFT)
        tk.Label(heading, text="Atlas", fg=_SIGNAL_TEAL, bg=_NIGHT_CHART, font=(_TYPEFACE, 13, "bold")).pack(anchor=tk.W)
        tk.Label(
            heading,
            text="Where should we begin?",
            fg=_STAR_PAPER,
            bg=_NIGHT_CHART,
            font=(_TYPEFACE, 30, "bold"),
        ).pack(anchor=tk.W, pady=(4, 0))
        self._session_clock = tk.Label(topbar, text="", fg=_SKY_MIST, bg=_NIGHT_CHART, font=(_TYPEFACE, 11))
        self._session_clock.pack(side=tk.RIGHT, pady=(12, 0))
        status_row = tk.Frame(content, bg=_NIGHT_CHART)
        status_row.pack(fill=tk.X, pady=(20, 12))
        self._mode_indicator = tk.Label(
            status_row,
            text="Local and private",
            fg=_SIGNAL_TEAL,
            bg=_NIGHT_CHART,
            font=(_TYPEFACE, 11, "bold"),
        )
        self._mode_indicator.pack(side=tk.LEFT)
        self._ghost_button(status_row, "Settings", self._open_settings_window).pack(side=tk.RIGHT)
        self._ghost_button(status_row, "Memory", self._open_memory_window).pack(side=tk.RIGHT, padx=(0, 8))

        transcript_shell = tk.Frame(content, bg=_NIGHT_CHART)
        transcript_shell.pack(fill=tk.BOTH, expand=True)
        transcript_header = tk.Frame(transcript_shell, bg=_NIGHT_CHART)
        transcript_header.pack(fill=tk.X, pady=(0, 4))
        tk.Label(
            transcript_header,
            text="This conversation",
            fg=_STAR_PAPER,
            bg=_NIGHT_CHART,
            font=(_TYPEFACE, 16, "bold"),
        ).pack(side=tk.LEFT)
        tk.Label(
            transcript_header,
            text="Responses stay on this Mac",
            fg=_SKY_MIST,
            bg=_NIGHT_CHART,
            font=(_TYPEFACE, 11),
        ).pack(side=tk.RIGHT)
        self._transcript = scrolledtext.ScrolledText(
            transcript_shell,
            wrap=tk.WORD,
            state=tk.DISABLED,
            bg=_NIGHT_CHART,
            fg=_STAR_PAPER,
            insertbackground=_SIGNAL_TEAL,
            relief=tk.FLAT,
            padx=0,
            pady=18,
            font=(_TYPEFACE, 14),
            highlightthickness=0,
        )
        self._transcript.pack(fill=tk.BOTH, expand=True)
        self._transcript.tag_configure("atlas", foreground=_SIGNAL_TEAL, font=(_TYPEFACE, 12, "bold"))
        self._transcript.tag_configure("user", foreground=_COPPER_BEARING, font=(_TYPEFACE, 12, "bold"))

        self._suggestion_bar = tk.Frame(content, bg=_NIGHT_CHART)
        self._suggestion_bar.pack(fill=tk.X, pady=(8, 0))
        self._render_suggestions(["What can Atlas help with?", "Help me plan next steps"])

        composer = tk.Frame(content, bg=_OBSERVATORY, highlightbackground=_MERIDIAN, highlightthickness=1)
        composer.pack(fill=tk.X, pady=(15, 0))
        composer_head = tk.Frame(composer, bg=_OBSERVATORY)
        composer_head.pack(fill=tk.X, padx=18, pady=(14, 0))
        tk.Label(
            composer_head,
            text="Speak or write your request",
            fg=_STAR_PAPER,
            bg=_OBSERVATORY,
            font=(_TYPEFACE, 14, "bold"),
        ).pack(side=tk.LEFT)
        self._input_status = tk.Label(
            composer_head,
            text="Press Return to send",
            fg=_SKY_MIST,
            bg=_OBSERVATORY,
            font=(_TYPEFACE, 10),
        )
        self._input_status.pack(side=tk.RIGHT)
        self._input_shell = tk.Frame(composer, bg=_NIGHT_CHART, highlightbackground=_MERIDIAN, highlightthickness=1)
        self._input_shell.pack(fill=tk.X, padx=18, pady=(9, 18))
        self._input = tk.Text(
            self._input_shell,
            height=3,
            wrap=tk.WORD,
            bg=_NIGHT_CHART,
            fg=_STAR_PAPER,
            insertbackground=_SIGNAL_TEAL,
            relief=tk.FLAT,
            padx=14,
            pady=11,
            font=(_TYPEFACE, 14),
            highlightthickness=0,
        )
        self._input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._input.bind("<Return>", self._send_event)
        self._input.bind("<Command-Return>", self._send_event)
        self._input.bind("<Control-Return>", self._send_event)
        self._input.bind("<KeyRelease>", self._update_input_status)
        self._input.bind("<FocusIn>", self._input_focus_in)
        self._input.bind("<FocusOut>", self._input_focus_out)
        self._send_button = self._command_label(
            self._input_shell,
            "Send",
            self._send,
            background=_SIGNAL_TEAL,
            foreground=_NIGHT_CHART,
            hover_background="#A6E0D9",
            hover_foreground=_NIGHT_CHART,
            padding_x=19,
            padding_y=12,
            font=(_TYPEFACE, 11, "bold"),
        )
        self._send_button.pack(side=tk.RIGHT, padx=10, pady=10)
        self._mic_button = tk.Label(
            self._input_shell,
            text="Hold to talk",
            bg=_COPPER_BEARING,
            fg=_NIGHT_CHART,
            font=(_TYPEFACE, 11, "bold"),
            padx=16,
            pady=12,
            cursor="hand2",
            highlightthickness=2,
            highlightbackground=_COPPER_BEARING,
            takefocus=True,
        )
        self._mic_button.pack(side=tk.RIGHT, padx=(0, 2), pady=10)
        self._mic_button.bind("<ButtonPress-1>", self._start_recording)
        self._mic_button.bind("<ButtonRelease-1>", self._stop_recording)
        self._mic_button.bind("<KeyPress-space>", self._start_recording)
        self._mic_button.bind("<KeyRelease-space>", self._stop_recording)
        self._mic_button.bind("<KeyPress-Return>", self._start_recording)
        self._mic_button.bind("<KeyRelease-Return>", self._stop_recording)
        self._mic_button.bind("<FocusIn>", self._mic_focus_in)
        self._mic_button.bind("<FocusOut>", self._mic_focus_out)
        self._input.focus_set()
        threading.Thread(target=self._prewarm_voice_input, daemon=True).start()
        self._refresh_field()
        self._animate_core()
        if self._voice_settings.enabled:
            self._root.after(350, self._start_startup_voice)

    @staticmethod
    def _command_label(
        parent: tk.Misc,
        text: str,
        command: Callable[[], None],
        *,
        background: str,
        foreground: str,
        hover_background: str,
        hover_foreground: str,
        padding_x: int,
        padding_y: int,
        font: tuple[str, int, str],
        anchor: Literal["w", "center"] = "center",
    ) -> tk.Label:
        """Create an accessible native control with pointer and keyboard support."""
        control = tk.Label(
            parent,
            text=text,
            anchor=anchor,
            bg=background,
            fg=foreground,
            font=font,
            padx=padding_x,
            pady=padding_y,
            cursor="hand2",
            highlightthickness=2,
            highlightbackground=background,
            takefocus=True,
        )

        def enter(_: tk.Event[tk.Misc]) -> None:
            if str(control.cget("state")) != "disabled":
                control.configure(bg=hover_background, fg=hover_foreground)

        def leave(_: tk.Event[tk.Misc]) -> None:
            control.configure(bg=background, fg=foreground)

        def focus_in(_: tk.Event[tk.Misc]) -> None:
            control.configure(highlightbackground=_FOCUS_RING)

        def focus_out(_: tk.Event[tk.Misc]) -> None:
            control.configure(highlightbackground=background)

        def activate(_: tk.Event[tk.Misc]) -> None:
            if str(control.cget("state")) != "disabled":
                command()

        control.bind("<Enter>", enter)
        control.bind("<Leave>", leave)
        control.bind("<Button-1>", activate)
        control.bind("<Return>", activate)
        control.bind("<space>", activate)
        control.bind("<FocusIn>", focus_in)
        control.bind("<FocusOut>", focus_out)
        return control

    @staticmethod
    def _navigation_button(parent: tk.Misc, text: str, command: Callable[[], None]) -> tk.Label:
        return AtlasDesktopApp._command_label(
            parent,
            text,
            command,
            background=_QUIET_BLUE,
            foreground=_STAR_PAPER,
            hover_background=_MERIDIAN,
            hover_foreground=_STAR_PAPER,
            padding_x=12,
            padding_y=9,
            font=(_TYPEFACE, 12, "bold"),
            anchor="w",
        )

    @staticmethod
    def _ghost_button(parent: tk.Misc, text: str, command: Callable[[], None]) -> tk.Label:
        return AtlasDesktopApp._command_label(
            parent,
            text,
            command,
            background=_NIGHT_CHART,
            foreground=_SKY_MIST,
            hover_background=_MERIDIAN,
            hover_foreground=_STAR_PAPER,
            padding_x=10,
            padding_y=6,
            font=(_TYPEFACE, 11, "bold"),
        )

    def _animate_core(self) -> None:
        """Draw Atlas's single deliberate motion: a celestial bearing while thinking."""
        if not self._core_canvas.winfo_exists():
            return
        canvas = self._core_canvas
        width = max(canvas.winfo_width(), 196)
        height = max(canvas.winfo_height(), 178)
        center_x, center_y = width / 2, height / 2 - 4
        canvas.delete("all")
        outer, inner = 64, 40
        canvas.create_oval(center_x - outer, center_y - outer, center_x + outer, center_y + outer, outline=_MERIDIAN, width=1)
        canvas.create_oval(center_x - inner, center_y - inner, center_x + inner, center_y + inner, outline=_SIGNAL_TEAL, width=2)
        canvas.create_line(center_x - outer - 10, center_y, center_x + outer + 10, center_y, fill=_MERIDIAN)
        canvas.create_line(center_x, center_y - outer - 10, center_x, center_y + outer + 10, fill=_MERIDIAN)
        bearing = self._core_phase if self._busy and not self._prefers_reduced_motion else 36
        canvas.create_arc(
            center_x - outer,
            center_y - outer,
            center_x + outer,
            center_y + outer,
            start=bearing,
            extent=62,
            style=tk.ARC,
            outline=_COPPER_BEARING,
            width=4,
        )
        canvas.create_oval(center_x - 10, center_y - 10, center_x + 10, center_y + 10, fill=_SIGNAL_TEAL, outline="")
        canvas.create_oval(center_x - 3, center_y - 3, center_x + 3, center_y + 3, fill=_STAR_PAPER, outline="")
        canvas.create_text(center_x, height - 13, text="Atlas bearing", fill=_SKY_MIST, font=(_TYPEFACE, 10))
        if self._busy and not self._prefers_reduced_motion:
            self._core_phase = (self._core_phase + 6) % 360
            self._root.after(90, self._animate_core)

    def _start_startup_voice(self) -> None:
        threading.Thread(target=self._speak_startup_voice, daemon=True).start()

    def _speak_startup_voice(self) -> None:
        asyncio.run(_speak_startup_sequence(self._speaker, self._voice_settings))

    def _refresh_field(self) -> None:
        now = datetime.now().astimezone().strftime("%I:%M %p %Z").lstrip("0")
        self._field_clock.configure(text=now)
        self._session_clock.configure(text=now)
        self._root.after(1_000, self._refresh_field)

    def _update_input_status(self, _: tk.Event[tk.Misc] | None = None) -> None:
        characters = len(self._input.get("1.0", "end-1c"))
        self._input_status.configure(
            text="Press Return to send" if characters == 0 else f"{characters} characters ready"
        )

    def _reflow_for_width(self, event: tk.Event[tk.Misc]) -> None:
        """Keep the conversation field useful in a compact desktop window."""
        if event.widget is not self._root:
            return
        compact = event.width < 980
        self._sidebar.configure(width=198 if compact else 244)
        self._brand_subtitle.configure(text="Local assistant" if compact else "Your private local assistant")
        self._core_canvas.configure(height=142 if compact else 178)

    def _mic_focus_in(self, _: tk.Event[tk.Misc]) -> None:
        self._mic_button.configure(highlightbackground=_FOCUS_RING)

    def _mic_focus_out(self, _: tk.Event[tk.Misc]) -> None:
        self._mic_button.configure(highlightbackground=_COPPER_BEARING)

    def _input_focus_in(self, _: tk.Event[tk.Misc]) -> None:
        self._input_shell.configure(highlightbackground=_FOCUS_RING)

    def _input_focus_out(self, _: tk.Event[tk.Misc]) -> None:
        self._input_shell.configure(highlightbackground=_MERIDIAN)

    def _animate_top_dot(self) -> None:
        """Compatibility hook for the original thinking indicator test."""
        self._animate_core()

    def _open_memory_window(self) -> None:
        window = tk.Toplevel(self._root)
        window.title("Atlas Memory")
        window.geometry("520x410")
        window.configure(bg=_NIGHT_CHART)
        tk.Label(window, text="Memory", fg=_STAR_PAPER, bg=_NIGHT_CHART, font=(_TYPEFACE, 22, "bold")).pack(anchor=tk.W, padx=26, pady=(26, 2))
        tk.Label(window, text="Only facts you explicitly asked Atlas to remember are listed here.", fg=_SKY_MIST, bg=_NIGHT_CHART, font=(_TYPEFACE, 11)).pack(anchor=tk.W, padx=26, pady=(0, 15))
        contents = scrolledtext.ScrolledText(window, wrap=tk.WORD, state=tk.DISABLED, bg=_OBSERVATORY, fg=_STAR_PAPER, relief=tk.FLAT, padx=14, pady=12, font=(_TYPEFACE, 12))
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

        def reset_style() -> None:
            if messagebox.askyesno(
                "Reset communication preferences",
                "Forget the response-style preferences Atlas inferred locally?",
                parent=window,
            ):
                threading.Thread(target=clear_style, daemon=True).start()

        def clear_style() -> None:
            asyncio.run(self._assistant.clear_communication_profile())

        controls = tk.Frame(window, bg=_NIGHT_CHART)
        controls.pack(fill=tk.X, padx=26, pady=20)
        self._command_label(controls, "Reset communication style", reset_style, background=_MERIDIAN, foreground=_STAR_PAPER, hover_background=_OBSERVATORY, hover_foreground=_STAR_PAPER, padding_x=12, padding_y=9, font=(_TYPEFACE, 10, "bold")).pack(side=tk.LEFT)
        self._command_label(controls, "Clear all memories", clear_all, background="#633849", foreground=_STAR_PAPER, hover_background="#835066", hover_foreground=_STAR_PAPER, padding_x=14, padding_y=9, font=(_TYPEFACE, 10, "bold")).pack(side=tk.RIGHT)

        refresh()

    def _open_action_history(self) -> None:
        window = tk.Toplevel(self._root)
        window.title("Atlas Action History")
        window.geometry("620x440")
        window.configure(bg=_NIGHT_CHART)
        tk.Label(window, text="Action history", fg=_STAR_PAPER, bg=_NIGHT_CHART, font=(_TYPEFACE, 22, "bold")).pack(anchor=tk.W, padx=26, pady=(26, 2))
        tk.Label(window, text="Local record of confirmation-gated actions. Clipboard contents are never recorded.", fg=_SKY_MIST, bg=_NIGHT_CHART, font=(_TYPEFACE, 11)).pack(anchor=tk.W, padx=26, pady=(0, 15))
        contents = scrolledtext.ScrolledText(window, wrap=tk.WORD, state=tk.DISABLED, bg=_OBSERVATORY, fg=_STAR_PAPER, relief=tk.FLAT, padx=14, pady=12, font=(_TYPEFACE, 12))
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

        self._command_label(window, "Clear action history", clear_all, background="#633849", foreground=_STAR_PAPER, hover_background="#835066", hover_foreground=_STAR_PAPER, padding_x=14, padding_y=9, font=(_TYPEFACE, 10, "bold")).pack(anchor=tk.E, padx=26, pady=20)
        refresh()

    def _open_settings_window(self) -> None:
        window = tk.Toplevel(self._root)
        window.title("Atlas settings")
        window.geometry("620x720")
        window.minsize(500, 590)
        window.configure(bg=_NIGHT_CHART)
        tk.Label(window, text="Settings", fg=_STAR_PAPER, bg=_NIGHT_CHART, font=(_TYPEFACE, 22, "bold")).pack(anchor=tk.W, padx=26, pady=(26, 2))
        tk.Label(window, text="Choose how Atlas sounds and responds on this Mac.", fg=_SKY_MIST, bg=_NIGHT_CHART, font=(_TYPEFACE, 11)).pack(anchor=tk.W, padx=26, pady=(0, 14))
        style = ttk.Style(window)
        style.configure("Atlas.TNotebook", background=_NIGHT_CHART, borderwidth=0)
        style.configure("Atlas.TNotebook.Tab", background=_NIGHT_CHART, foreground=_SKY_MIST, font=(_TYPEFACE, 11, "bold"), padding=(14, 8))
        style.map("Atlas.TNotebook.Tab", background=[("selected", _OBSERVATORY)], foreground=[("selected", _STAR_PAPER)])
        tabs = ttk.Notebook(window, style="Atlas.TNotebook")
        tabs.pack(fill=tk.BOTH, expand=True, padx=26)
        voice_tab = tk.Frame(tabs, bg=_OBSERVATORY)
        tabs.add(voice_tab, text="Voice")
        voice_enabled = tk.BooleanVar(value=self._voice_settings.enabled)
        voice_engine = tk.StringVar(value=self._voice_settings.engine)
        neural_voice = tk.StringVar(value=self._voice_settings.neural_voice)
        voice_type = tk.StringVar(value=self._voice_settings.voice)
        option_style: dict[str, Any] = {
            "bg": _OBSERVATORY,
            "fg": _STAR_PAPER,
            "selectcolor": _OBSERVATORY,
            "activebackground": _OBSERVATORY,
            "activeforeground": _STAR_PAPER,
            "font": (_TYPEFACE, 11),
        }
        tk.Checkbutton(voice_tab, text="Read Atlas responses aloud", variable=voice_enabled, **option_style).pack(anchor=tk.W, padx=20, pady=(20, 14))
        tk.Label(voice_tab, text="Voice engine", fg=_SIGNAL_TEAL, bg=_OBSERVATORY, font=(_TYPEFACE, 11, "bold")).pack(anchor=tk.W, padx=20)
        tk.Radiobutton(voice_tab, text="Local neural voice (recommended)", variable=voice_engine, value="neural", **option_style).pack(anchor=tk.W, padx=20, pady=(4, 0))
        tk.Label(voice_tab, text="More natural speech, synthesized and played entirely on this Mac.", fg=_SKY_MIST, bg=_OBSERVATORY, font=(_TYPEFACE, 10)).pack(anchor=tk.W, padx=42)
        tk.Radiobutton(voice_tab, text="macOS system voice", variable=voice_engine, value="system", **option_style).pack(anchor=tk.W, padx=20, pady=(7, 0))
        tk.Label(voice_tab, text="Used automatically if the selected neural voice is not installed.", fg=_SKY_MIST, bg=_OBSERVATORY, font=(_TYPEFACE, 10)).pack(anchor=tk.W, padx=42)
        neural_status = tk.Label(voice_tab, fg=_COPPER_BEARING, bg=_OBSERVATORY, font=(_TYPEFACE, 10, "bold"))
        neural_status.pack(anchor=tk.W, padx=20, pady=(10, 0))
        tk.Label(voice_tab, text="Neural voice", fg=_SIGNAL_TEAL, bg=_OBSERVATORY, font=(_TYPEFACE, 11, "bold")).pack(anchor=tk.W, padx=20, pady=(12, 0))
        for voice_id, (name, description, _) in NEURAL_VOICE_OPTIONS.items():
            tk.Radiobutton(voice_tab, text=f"{name}: {description}", variable=neural_voice, value=voice_id, **option_style).pack(anchor=tk.W, padx=20, pady=1)
        tk.Label(voice_tab, text="macOS fallback voice", fg=_SIGNAL_TEAL, bg=_OBSERVATORY, font=(_TYPEFACE, 11, "bold")).pack(anchor=tk.W, padx=20, pady=(10, 0))
        for voice_id, (name, description, _, _) in VOICE_OPTIONS.items():
            tk.Radiobutton(voice_tab, text=f"{name}: {description}", variable=voice_type, value=voice_id, **option_style).pack(anchor=tk.W, padx=20, pady=2)

        def refresh_neural_status(*_: str) -> None:
            if self._speaker.is_neural_voice_ready(neural_voice.get()):
                neural_status.configure(text="Selected neural model installed and ready.", fg=_SIGNAL_TEAL)
            else:
                neural_status.configure(
                    text="Selected neural model not installed. Atlas will use the macOS fallback.",
                    fg=_COPPER_BEARING,
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

        buttons = tk.Frame(window, bg=_NIGHT_CHART)
        buttons.pack(fill=tk.X, padx=26, pady=22)
        self._command_label(buttons, "Test voice", test_voice, background=_MERIDIAN, foreground=_STAR_PAPER, hover_background=_OBSERVATORY, hover_foreground=_STAR_PAPER, padding_x=14, padding_y=9, font=(_TYPEFACE, 10, "bold")).pack(side=tk.LEFT)
        self._command_label(buttons, "Save settings", save, background=_SIGNAL_TEAL, foreground=_NIGHT_CHART, hover_background="#A6E0D9", hover_foreground=_NIGHT_CHART, padding_x=14, padding_y=9, font=(_TYPEFACE, 10, "bold")).pack(side=tk.RIGHT)

    def _set_field_state(self, state: str) -> None:
        self._field_state = state
        if state == "PROCESSING":
            self._field_state_label.configure(text="Following your bearing", fg=_COPPER_BEARING)
            self._mode_indicator.configure(text="Thinking locally", fg=_COPPER_BEARING)
        else:
            self._field_state_label.configure(text="Local and ready", fg=_SIGNAL_TEAL)
            self._mode_indicator.configure(text="Local and private", fg=_SIGNAL_TEAL)
        self._animate_core()

    def _append(self, speaker: str, message: str) -> None:
        self._transcript.configure(state=tk.NORMAL)
        tag = "atlas" if speaker == self._name else "user"
        self._transcript.insert(tk.END, f"{speaker}\n", tag)
        self._transcript.insert(tk.END, f"{message}\n\n")
        self._transcript.configure(state=tk.DISABLED)
        self._transcript.see(tk.END)

    def _render_suggestions(self, suggestions: list[str]) -> None:
        """Show reusable, safe follow-ups under the conversation stream."""
        for child in self._suggestion_bar.winfo_children():
            child.destroy()
        if not suggestions:
            return
        tk.Label(
            self._suggestion_bar,
            text="Suggested next step",
            fg=_SKY_MIST,
            bg=_NIGHT_CHART,
            font=(_TYPEFACE, 10, "bold"),
        ).pack(side=tk.LEFT, padx=(2, 8))
        for suggestion in suggestions[:2]:
            self._command_label(
                self._suggestion_bar,
                suggestion,
                self._suggestion_command(suggestion),
                background=_MERIDIAN,
                foreground=_STAR_PAPER,
                hover_background=_OBSERVATORY,
                hover_foreground=_STAR_PAPER,
                padding_x=10,
                padding_y=6,
                font=(_TYPEFACE, 10, "bold"),
            ).pack(side=tk.LEFT, padx=(0, 7))

    def _suggestion_command(self, suggestion: str) -> Callable[[], None]:
        def use_suggestion() -> None:
            self._use_suggestion(suggestion)

        return use_suggestion

    def _use_suggestion(self, suggestion: str) -> None:
        if self._busy:
            return
        self._input.delete("1.0", tk.END)
        self._input.insert("1.0", suggestion)
        self._update_input_status()
        self._input.focus_set()

    def _send_event(self, event: tk.Event[tk.Misc]) -> str:
        self._send()
        return "break"

    def _start_recording(self, _: tk.Event[tk.Misc] | None) -> None:
        if self._busy or self._recording:
            return
        try:
            self._voice_input.start()
        except VoiceInputError as exc:
            self._input_status.configure(text="Voice input setup required")
            messagebox.showinfo("Voice input", str(exc), parent=self._root)
            return
        self._recording = True
        threading.Thread(target=self._play_listening_cue, daemon=True).start()
        self._mic_button.configure(text="Listening… release", bg="#9E5E45", fg=_STAR_PAPER)
        self._input_status.configure(text="Listening locally. Release when you are done.")

    def _stop_recording(self, _: tk.Event[tk.Misc]) -> None:
        if not self._recording:
            return
        self._recording = False
        self._mic_button.configure(text="Transcribing…", bg=_MERIDIAN, fg=_STAR_PAPER)
        threading.Thread(target=self._transcribe_recording, daemon=True).start()

    def _transcribe_recording(self) -> None:
        try:
            transcript = asyncio.run(self._voice_input.stop_and_transcribe())
        except VoiceInputError as exc:
            self._root.after(0, self._voice_input_failed, str(exc))
            return
        self._root.after(0, self._voice_input_ready, transcript)

    def _voice_input_ready(self, transcript: str) -> None:
        self._mic_button.configure(text="Hold to talk", bg=_COPPER_BEARING, fg=_NIGHT_CHART)
        if not transcript or is_ambiguous_voice_transcript(transcript):
            self._voice_input_unintelligible()
            return
        normalized = normalize_voice_transcript(transcript)
        if is_ambiguous_voice_transcript(normalized):
            self._voice_input_unintelligible()
        else:
            self._send(normalized, acknowledge_voice_wait=True)
        self._input.focus_set()

    def _voice_input_unintelligible(self) -> None:
        reply = "I’m sorry, I was unable to transcribe your voice message. Please try again!"
        self._input_status.configure(text="Voice message unclear")
        self._append(self._name, reply)
        if self._voice_settings.enabled:
            threading.Thread(target=self._speak_fixed_reply, args=(reply,), daemon=True).start()

    def _speak_fixed_reply(self, reply: str) -> None:
        asyncio.run(self._speaker.speak(reply, self._voice_settings))

    def _voice_input_failed(self, error: str) -> None:
        self._mic_button.configure(text="Hold to talk", bg=_COPPER_BEARING, fg=_NIGHT_CHART)
        self._input_status.configure(text="Voice input unavailable")
        messagebox.showerror("Voice input", error, parent=self._root)

    def _send(self, voice_message: str | None = None, *, acknowledge_voice_wait: bool = False) -> None:
        if self._busy:
            return
        message = voice_message or self._input.get("1.0", tk.END).strip()
        if not message:
            return
        self._input.delete("1.0", tk.END)
        self._update_input_status()
        self._append("You", message)
        self._busy = True
        self._set_field_state("PROCESSING")
        self._send_button.configure(state=tk.DISABLED, text="Thinking…")
        if acknowledge_voice_wait:
            self._voice_ack_token += 1
            token = self._voice_ack_token
            self._root.after(1_300, self._acknowledge_long_voice_request, token)
        threading.Thread(target=self._reply, args=(message,), daemon=True).start()

    def _acknowledge_long_voice_request(self, token: int) -> None:
        if self._busy and token == self._voice_ack_token and self._voice_settings.enabled:
            threading.Thread(target=self._speak_processing_acknowledgement, daemon=True).start()

    def _speak_processing_acknowledgement(self) -> None:
        asyncio.run(self._speaker.speak("One moment, sir.", self._voice_settings))

    def _prewarm_voice_input(self) -> None:
        """Keep first push-to-talk use responsive without blocking the command deck."""
        try:
            asyncio.run(self._voice_input.prewarm())
        except OSError:
            logging.getLogger("atlas.app").info("voice_input_prewarm_unavailable")

    def _play_listening_cue(self) -> None:
        asyncio.run(_play_system_sound("Glass"))

    def _reply(self, message: str) -> None:
        try:
            reply = asyncio.run(self._assistant.handle_message(message))
            suggestions = asyncio.run(self._assistant.suggestions_for(message, reply))
        except Exception:
            logging.getLogger("atlas.app").exception("desktop chat request failed")
            reply = "I’m unable to complete that request right now."
            suggestions = []
        self._root.after(0, self._finish_reply, reply, suggestions)

    def _finish_reply(self, reply: str, suggestions: list[str]) -> None:
        if self._voice_settings.enabled:
            spoken_reply = _speech_text(reply)
            self._begin_spoken_reply()
            threading.Thread(target=self._speak_reply, args=(spoken_reply,), daemon=True).start()
        else:
            self._append(self._name, reply)
        self._busy = False
        self._voice_ack_token += 1
        self._set_field_state("READY")
        self._send_button.configure(state=tk.NORMAL, text="Send")
        self._render_suggestions(suggestions)
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
    llm = OllamaProvider(host=config.ollama_host, model=config.llm_model, temperature=config.llm_temperature, timeout=config.llm_request_timeout_seconds, context_tokens=config.llm_context_tokens, max_response_tokens=config.llm_max_response_tokens, think=config.llm_think, keep_alive=config.llm_keep_alive)
    if not await llm.is_available():
        raise RuntimeError(f"Could not reach Ollama at {config.ollama_host}.")
    await llm.warm()
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
        self._window.configure(bg=_NIGHT_CHART)
        self._window.geometry("600x430")
        self._window.update_idletasks()
        x = (self._window.winfo_screenwidth() - 600) // 2
        y = (self._window.winfo_screenheight() - 430) // 2
        self._window.geometry(f"600x430+{x}+{y}")
        self._phase = 0
        self._build()

    def _build(self) -> None:
        frame = tk.Frame(self._window, bg=_NIGHT_CHART, highlightbackground=_MERIDIAN, highlightthickness=1)
        frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        tk.Label(frame, text="Atlas", fg=_SIGNAL_TEAL, bg=_NIGHT_CHART, font=(_TYPEFACE, 13, "bold")).pack(anchor=tk.W, padx=30, pady=(28, 0))
        self._radar = tk.Canvas(frame, height=195, bg=_NIGHT_CHART, highlightthickness=0)
        self._radar.pack(fill=tk.X, pady=(3, 0))
        tk.Label(frame, text="Preparing your local assistant", fg=_STAR_PAPER, bg=_NIGHT_CHART, font=(_TYPEFACE, 24, "bold")).pack()
        tk.Label(frame, text="Your conversations and controls remain on this Mac.", fg=_SKY_MIST, bg=_NIGHT_CHART, font=(_TYPEFACE, 11)).pack(pady=(3, 14))
        self._status = tk.Label(frame, text="Checking the local connection…", fg=_STAR_PAPER, bg=_NIGHT_CHART, font=(_TYPEFACE, 13, "bold"))
        self._status.pack()
        self._detail = tk.Label(frame, text="Ollama local session", fg=_SKY_MIST, bg=_NIGHT_CHART, font=(_TYPEFACE, 10))
        self._detail.pack(pady=(5, 0))
        self._retry = AtlasDesktopApp._command_label(frame, "Retry connection", self.start_check, background=_SIGNAL_TEAL, foreground=_NIGHT_CHART, hover_background="#A6E0D9", hover_foreground=_NIGHT_CHART, padding_x=14, padding_y=8, font=(_TYPEFACE, 10, "bold"))
        self._animate()
        self.start_check()

    def _animate(self) -> None:
        if not self._window.winfo_exists():
            return
        self._radar.delete("all")
        width = max(self._radar.winfo_width(), 600)
        center_x, center_y = width / 2, 96
        for radius, color, line_width in ((78, _MERIDIAN, 1), (54, _SIGNAL_TEAL, 2)):
            self._radar.create_oval(center_x - radius, center_y - radius, center_x + radius, center_y + radius, outline=color, width=line_width)
        self._radar.create_arc(center_x - 78, center_y - 78, center_x + 78, center_y + 78, start=self._phase, extent=68, style=tk.ARC, outline=_COPPER_BEARING, width=4)
        self._radar.create_oval(center_x - 10, center_y - 10, center_x + 10, center_y + 10, fill=_SIGNAL_TEAL, outline="")
        self._radar.create_oval(center_x - 3, center_y - 3, center_x + 3, center_y + 3, fill=_STAR_PAPER, outline="")
        self._radar.create_text(center_x, center_y + 116, text="Establishing local link", fill=_SKY_MIST, font=(_TYPEFACE, 10))
        self._phase += 8
        self._window.after(80, self._animate)

    def start_check(self) -> None:
        self._retry.pack_forget()
        self._status.configure(text="Checking the local connection…", fg=_STAR_PAPER)
        self._detail.configure(text=f"{platform.system()} local session")
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
        self._status.configure(text="Local connection verified", fg=_SIGNAL_TEAL)
        self._detail.configure(text="Opening Atlas")
        self._window.after(650, lambda: self._launch(assistant, voice_settings))

    def _failed(self, error: str) -> None:
        self._status.configure(text="Connection unavailable", fg=_COPPER_BEARING)
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
            self._config.voice_input_models_dir,
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
