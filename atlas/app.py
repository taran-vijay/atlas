"""Native desktop interface for Atlas.

This module keeps the assistant local: it talks directly to the same core used
by the CLI and never starts a browser server.
"""
from __future__ import annotations

import asyncio
import logging
import platform
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, scrolledtext
from typing import Protocol

from atlas.cli import _build_tool_registry, _configure_logging
from atlas.core.assistant.core import AssistantCore
from atlas.core.config.schema import AtlasConfig
from atlas.core.llm.ollama_provider import OllamaProvider
from atlas.core.memory.base import SavedMemory
from atlas.core.memory.sqlite_store import SQLiteMemoryStore
from atlas.core.tools.registry import ConfirmationCallback

_DEVICE_ASSET = Path(__file__).parent / "assets" / "atlas-device-core.png"


class HandlesMessage(Protocol):
    async def handle_message(self, user_input: str) -> str: ...


class HandlesMemory(HandlesMessage, Protocol):
    async def list_saved_memories(self) -> list[SavedMemory]: ...

    async def clear_saved_memories(self) -> None: ...


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
        return "perform an action", f"Tool: {tool_name}"


class AtlasDesktopApp:
    def __init__(self, root: tk.Tk, assistant: HandlesMemory, name: str) -> None:
        self._root = root
        self._assistant = assistant
        self._name = name
        self._busy = False
        self._field_state = "READY"
        self._thinking = False
        self._thinking_frame = 0
        self._configure_window()
        self._build_interface()

    def _configure_window(self) -> None:
        self._root.title(f"{self._name} // Local Core")
        self._root.geometry("1120x740")
        self._root.minsize(760, 520)
        self._root.configure(bg="#070b12")

    def _build_interface(self) -> None:
        sidebar = tk.Frame(self._root, bg="#0c1420", width=250)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        brand = tk.Frame(sidebar, bg="#0c1420")
        brand.pack(anchor=tk.W, padx=24, pady=(30, 4))
        self._top_dot = tk.Label(brand, text="◉", fg="#73e0d4", bg="#0c1420", font=("Helvetica", 19, "bold"))
        self._top_dot.pack(side=tk.LEFT)
        tk.Label(brand, text="  ATLAS", fg="#73e0d4", bg="#0c1420", font=("Helvetica", 19, "bold")).pack(side=tk.LEFT)
        tk.Label(sidebar, text="ORBITAL LOCAL INTELLIGENCE", fg="#7e90a6", bg="#0c1420", font=("Helvetica", 9, "bold")).pack(
            anchor=tk.W, padx=25
        )
        core = tk.Canvas(sidebar, height=145, bg="#0c1420", highlightthickness=0)
        core.pack(fill=tk.X, padx=24, pady=(22, 12))
        for offset, color in ((8, "#183448"), (25, "#235469"), (43, "#397d85")):
            core.create_oval(73 - offset, 72 - offset, 73 + offset, 72 + offset, outline=color, width=2)
        core.create_oval(67, 66, 79, 78, fill="#f6b73c", outline="")
        core.create_line(0, 72, 48, 72, fill="#2a5369")
        core.create_line(98, 72, 150, 72, fill="#2a5369")
        tk.Frame(sidebar, height=2, bg="#203043").pack(fill=tk.X, padx=24, pady=(0, 22))
        tk.Label(sidebar, text="PRIVATE SESSION", fg="#7e90a6", bg="#0c1420", font=("Helvetica", 9, "bold")).pack(
            anchor=tk.W, padx=25
        )
        tk.Label(sidebar, text="Encrypted by locality.\nNever leaves this Mac.", justify=tk.LEFT, fg="#dce9f3", bg="#0c1420", font=("Helvetica", 12)).pack(
            anchor=tk.W, padx=25, pady=(7, 0)
        )
        field = tk.Frame(sidebar, bg="#0a111b", highlightbackground="#2d7080", highlightthickness=1)
        field.pack(fill=tk.X, padx=20, pady=(24, 0))
        tk.Label(field, text="ATLAS FIELD // 01", fg="#73e0d4", bg="#0a111b", font=("Helvetica", 9, "bold")).pack(anchor=tk.W, padx=14, pady=(13, 3))
        self._field_state_label = tk.Label(field, text="◈  READY", fg="#f6c35c", bg="#0a111b", font=("Helvetica", 13, "bold"))
        self._field_state_label.pack(anchor=tk.W, padx=14)
        self._field_clock = tk.Label(field, text="", fg="#93a9bb", bg="#0a111b", font=("Helvetica", 9))
        self._field_clock.pack(anchor=tk.W, padx=14, pady=(3, 1))
        tk.Label(field, text="12 TOOLS  ·  LOCAL MEMORY", fg="#60768a", bg="#0a111b", font=("Helvetica", 8, "bold")).pack(anchor=tk.W, padx=14, pady=(0, 13))
        tk.Button(sidebar, text="REVIEW MEMORIES", command=self._open_memory_window, bg="#162536", fg="#73e0d4", activebackground="#23445a", activeforeground="#e7fffc", relief=tk.FLAT, font=("Helvetica", 9, "bold"), padx=12, pady=9).pack(fill=tk.X, padx=20, pady=(14, 0))
        device = tk.Frame(sidebar, bg="#08111c", highlightbackground="#24455b", highlightthickness=1)
        device.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=24)
        self._device_image: tk.PhotoImage | None
        try:
            self._device_image = tk.PhotoImage(file=str(_DEVICE_ASSET)).subsample(7, 7)
        except tk.TclError:
            self._device_image = None
        if self._device_image is not None:
            tk.Label(device, image=self._device_image, bg="#08111c").pack(pady=(10, 0))
        tk.Label(device, text="MAC // LOCAL CORE", fg="#73e0d4", bg="#08111c", font=("Helvetica", 9, "bold")).pack(pady=(2, 0))
        tk.Label(device, text="Private inference online", fg="#7890a3", bg="#08111c", font=("Helvetica", 9)).pack(pady=(2, 12))

        content = tk.Frame(self._root, bg="#070b12")
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(18, 24), pady=24)
        header = tk.Frame(content, bg="#101923", highlightbackground="#24455b", highlightthickness=1)
        header.pack(fill=tk.X)
        tk.Label(header, text="ATLAS // COMMAND SURFACE", fg="#73e0d4", bg="#101923", font=("Helvetica", 9, "bold")).pack(anchor=tk.W, padx=24, pady=(19, 2))
        tk.Label(header, text="What are we solving?", fg="#edf7ff", bg="#101923", font=("Helvetica", 23, "bold")).pack(anchor=tk.W, padx=24)
        tk.Label(header, text="Your Personal AI Assistant", fg="#9cb0c3", bg="#101923", font=("Helvetica", 11)).pack(anchor=tk.W, padx=24, pady=(2, 19))

        self._transcript = scrolledtext.ScrolledText(content, wrap=tk.WORD, state=tk.DISABLED, bg="#0e1620", fg="#e9edf2", insertbackground="#e9edf2", relief=tk.FLAT, padx=24, pady=20, font=("Helvetica", 12))
        self._transcript.pack(fill=tk.BOTH, expand=True, pady=(1, 0))
        self._transcript.tag_configure("atlas", foreground="#73e0d4", font=("Helvetica", 10, "bold"))
        self._transcript.tag_configure("user", foreground="#f6c35c", font=("Helvetica", 10, "bold"))
        self._append("Atlas", "Hello — I’m Atlas. What would you like to work on?")

        composer = tk.Frame(content, bg="#101923", highlightbackground="#24455b", highlightthickness=1)
        composer.pack(fill=tk.X, pady=(1, 0))
        self._input = tk.Text(composer, height=3, wrap=tk.WORD, bg="#091019", fg="#e9edf2", insertbackground="#73e0d4", relief=tk.FLAT, padx=12, pady=10, font=("Helvetica", 12))
        self._input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(14, 8), pady=14)
        self._input.bind("<Return>", self._send_event)
        self._input.bind("<Command-Return>", self._send_event)
        self._input.bind("<Control-Return>", self._send_event)
        self._send_button = tk.Button(composer, text="Transmit", command=self._send, bg="#73e0d4", fg="#061210", activebackground="#a4fff6", relief=tk.FLAT, font=("Helvetica", 11, "bold"), padx=22, pady=12)
        self._send_button.pack(side=tk.RIGHT, padx=(0, 14), pady=14)
        self._input.focus_set()
        self._refresh_field()

    def _refresh_field(self) -> None:
        now = datetime.now().astimezone().strftime("LOCAL TIME  %H:%M:%S  %Z")
        self._field_clock.configure(text=now)
        self._root.after(1_000, self._refresh_field)

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

        tk.Button(window, text="CLEAR ALL MEMORIES", command=clear_all, bg="#3d2028", fg="#ffb5bc", activebackground="#642b36", relief=tk.FLAT, font=("Helvetica", 9, "bold"), padx=12, pady=9).pack(anchor=tk.E, padx=22, pady=18)
        refresh()

    def _set_field_state(self, state: str) -> None:
        self._field_state = state
        colors = {"READY": "#f6c35c", "PROCESSING": "#73e0d4"}
        marker = "◈" if state == "READY" else "◌"
        self._field_state_label.configure(text=f"{marker}  {state}", fg=colors[state])
        self._thinking = state == "PROCESSING"
        if self._thinking:
            self._animate_top_dot()
        else:
            self._top_dot.configure(text="◉", fg="#73e0d4")

    def _animate_top_dot(self) -> None:
        if not self._thinking:
            return
        frames = ("◔", "◑", "◕", "◒")
        self._top_dot.configure(text=frames[self._thinking_frame % len(frames)], fg="#f6c35c")
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
        self._append("You", message)
        self._busy = True
        self._set_field_state("PROCESSING")
        self._send_button.configure(state=tk.DISABLED, text="Thinking…")
        threading.Thread(target=self._reply, args=(message,), daemon=True).start()

    def _reply(self, message: str) -> None:
        try:
            reply = asyncio.run(self._assistant.handle_message(message))
        except Exception:
            logging.getLogger("atlas.app").exception("desktop chat request failed")
            reply = "I’m unable to complete that request right now."
        self._root.after(0, self._finish_reply, reply)

    def _finish_reply(self, reply: str) -> None:
        self._append(self._name, reply)
        self._busy = False
        self._set_field_state("READY")
        self._send_button.configure(state=tk.NORMAL, text="Send")
        self._input.focus_set()


async def _create_assistant(
    config: AtlasConfig, *, confirm: ConfirmationCallback | None = None
) -> AssistantCore:
    llm = OllamaProvider(host=config.ollama_host, model=config.llm_model, temperature=config.llm_temperature, timeout=config.llm_request_timeout_seconds)
    if not await llm.is_available():
        raise RuntimeError(f"Could not reach Ollama at {config.ollama_host}.")
    return AssistantCore(assistant_name=config.assistant_name, llm=llm, memory=SQLiteMemoryStore(config.memory_db_path), tools=_build_tool_registry(confirm=confirm), max_history_turns=config.memory_max_turns)


class ConnectionScreen:
    """macOS-friendly launch surface that stays responsive during the Ollama check."""

    def __init__(self, root: tk.Tk, config: AtlasConfig) -> None:
        self._root = root
        self._config = config
        self._confirmation = DesktopConfirmationBridge(root)
        self._window = tk.Toplevel(root)
        self._window.overrideredirect(True)
        self._window.configure(bg="#070b12")
        self._window.geometry("500x330")
        self._window.update_idletasks()
        x = (self._window.winfo_screenwidth() - 500) // 2
        y = (self._window.winfo_screenheight() - 330) // 2
        self._window.geometry(f"500x330+{x}+{y}")
        self._phase = 0
        self._build()

    def _build(self) -> None:
        frame = tk.Frame(self._window, bg="#070b12", highlightbackground="#24455b", highlightthickness=1)
        frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)
        self._radar = tk.Canvas(frame, height=145, bg="#070b12", highlightthickness=0)
        self._radar.pack(fill=tk.X, pady=(30, 0))
        tk.Label(frame, text="ATLAS", fg="#eaf7ff", bg="#070b12", font=("Helvetica", 25, "bold")).pack()
        tk.Label(frame, text="LOCAL CORE INITIALIZATION", fg="#73e0d4", bg="#070b12", font=("Helvetica", 9, "bold")).pack(pady=(2, 12))
        self._status = tk.Label(frame, text="Checking local inference connection…", fg="#a7b7c8", bg="#070b12", font=("Helvetica", 12))
        self._status.pack()
        self._detail = tk.Label(frame, text="Ollama / macOS local mode", fg="#64768a", bg="#070b12", font=("Helvetica", 10))
        self._detail.pack(pady=(5, 0))
        self._retry = tk.Button(frame, text="Retry connection", command=self.start_check, bg="#73e0d4", fg="#061210", relief=tk.FLAT, font=("Helvetica", 10, "bold"))
        self._animate()
        self.start_check()

    def _animate(self) -> None:
        if not self._window.winfo_exists():
            return
        self._radar.delete("all")
        center_x, center_y = 250, 72
        for radius, color in ((18, "#1d4e64"), (36, "#235a70"), (56, "#2f7884")):
            self._radar.create_oval(center_x - radius, center_y - radius, center_x + radius, center_y + radius, outline=color, width=2)
        angle = self._phase % 120
        end_x = center_x + 55 * ((angle - 60) / 60)
        self._radar.create_line(center_x, center_y, end_x, center_y - 36, fill="#73e0d4", width=2)
        self._radar.create_oval(center_x - 7, center_y - 7, center_x + 7, center_y + 7, fill="#f6c35c", outline="")
        self._phase += 8
        self._window.after(80, self._animate)

    def start_check(self) -> None:
        self._retry.pack_forget()
        self._status.configure(text="Checking local inference connection…", fg="#a7b7c8")
        self._detail.configure(text=f"Ollama / {platform.system()} local mode")
        threading.Thread(target=self._connect, daemon=True).start()

    def _connect(self) -> None:
        try:
            assistant = asyncio.run(_create_assistant(self._config, confirm=self._confirmation.confirm))
        except RuntimeError as exc:
            self._root.after(0, self._failed, str(exc))
            return
        self._root.after(0, self._ready, assistant)

    def _ready(self, assistant: AssistantCore) -> None:
        self._status.configure(text="Local core verified", fg="#73e0d4")
        self._detail.configure(text="Ollama is online · launching command surface")
        self._window.after(650, lambda: self._launch(assistant))

    def _failed(self, error: str) -> None:
        self._status.configure(text="Connection unavailable", fg="#f6c35c")
        self._detail.configure(text=error)
        self._retry.pack(pady=(16, 0))

    def _launch(self, assistant: AssistantCore) -> None:
        self._window.destroy()
        self._root.deiconify()
        AtlasDesktopApp(self._root, assistant, self._config.assistant_name)


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
