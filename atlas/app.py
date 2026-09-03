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
from tkinter import scrolledtext
from typing import Protocol

from atlas.cli import _build_tool_registry, _configure_logging
from atlas.core.assistant.core import AssistantCore
from atlas.core.config.schema import AtlasConfig
from atlas.core.llm.ollama_provider import OllamaProvider
from atlas.core.memory.sqlite_store import SQLiteMemoryStore


class HandlesMessage(Protocol):
    async def handle_message(self, user_input: str) -> str: ...


class AtlasDesktopApp:
    def __init__(self, root: tk.Tk, assistant: HandlesMessage, name: str) -> None:
        self._root = root
        self._assistant = assistant
        self._name = name
        self._busy = False
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
        tk.Label(sidebar, text="◉  ATLAS", fg="#73e0d4", bg="#0c1420", font=("Helvetica", 19, "bold")).pack(
            anchor=tk.W, padx=24, pady=(30, 4)
        )
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
        status = tk.Frame(sidebar, bg="#101b29", highlightbackground="#24455b", highlightthickness=1)
        status.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=24)
        tk.Label(status, text="●  CORE ONLINE", fg="#73e0d4", bg="#101b29", font=("Helvetica", 10, "bold")).pack(anchor=tk.W, padx=14, pady=(13, 3))
        tk.Label(status, text="Ollama // local inference", fg="#9cb0c3", bg="#101b29", font=("Helvetica", 10)).pack(anchor=tk.W, padx=14, pady=(0, 13))

        content = tk.Frame(self._root, bg="#070b12")
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(18, 24), pady=24)
        header = tk.Frame(content, bg="#101923", highlightbackground="#24455b", highlightthickness=1)
        header.pack(fill=tk.X)
        tk.Label(header, text="ATLAS // COMMAND SURFACE", fg="#73e0d4", bg="#101923", font=("Helvetica", 9, "bold")).pack(anchor=tk.W, padx=24, pady=(19, 2))
        tk.Label(header, text="What are we solving?", fg="#edf7ff", bg="#101923", font=("Helvetica", 23, "bold")).pack(anchor=tk.W, padx=24)
        tk.Label(header, text="Natural conversation · local tools · explicit boundaries", fg="#9cb0c3", bg="#101923", font=("Helvetica", 11)).pack(anchor=tk.W, padx=24, pady=(2, 19))

        self._transcript = scrolledtext.ScrolledText(content, wrap=tk.WORD, state=tk.DISABLED, bg="#0e1620", fg="#e9edf2", insertbackground="#e9edf2", relief=tk.FLAT, padx=24, pady=20, font=("Helvetica", 12))
        self._transcript.pack(fill=tk.BOTH, expand=True, pady=(1, 0))
        self._transcript.tag_configure("atlas", foreground="#73e0d4", font=("Helvetica", 10, "bold"))
        self._transcript.tag_configure("user", foreground="#f6c35c", font=("Helvetica", 10, "bold"))
        self._append("Atlas", "Hello — I’m Atlas. What would you like to work on?")

        composer = tk.Frame(content, bg="#101923", highlightbackground="#24455b", highlightthickness=1)
        composer.pack(fill=tk.X, pady=(1, 0))
        self._input = tk.Text(composer, height=3, wrap=tk.WORD, bg="#091019", fg="#e9edf2", insertbackground="#73e0d4", relief=tk.FLAT, padx=12, pady=10, font=("Helvetica", 12))
        self._input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(14, 8), pady=14)
        self._input.bind("<Command-Return>", self._send_event)
        self._input.bind("<Control-Return>", self._send_event)
        self._send_button = tk.Button(composer, text="Transmit", command=self._send, bg="#73e0d4", fg="#061210", activebackground="#a4fff6", relief=tk.FLAT, font=("Helvetica", 11, "bold"), padx=22, pady=12)
        self._send_button.pack(side=tk.RIGHT, padx=(0, 14), pady=14)
        self._input.focus_set()

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
        self._send_button.configure(state=tk.NORMAL, text="Send")
        self._input.focus_set()


async def _create_assistant(config: AtlasConfig) -> AssistantCore:
    llm = OllamaProvider(host=config.ollama_host, model=config.llm_model, temperature=config.llm_temperature, timeout=config.llm_request_timeout_seconds)
    if not await llm.is_available():
        raise RuntimeError(f"Could not reach Ollama at {config.ollama_host}.")
    return AssistantCore(assistant_name=config.assistant_name, llm=llm, memory=SQLiteMemoryStore(config.memory_db_path), tools=_build_tool_registry(), max_history_turns=config.memory_max_turns)


class ConnectionScreen:
    """macOS-friendly launch surface that stays responsive during the Ollama check."""

    def __init__(self, root: tk.Tk, config: AtlasConfig) -> None:
        self._root = root
        self._config = config
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
            assistant = asyncio.run(_create_assistant(self._config))
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
