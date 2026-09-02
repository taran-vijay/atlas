"""Native desktop interface for Atlas.

This module keeps the assistant local: it talks directly to the same core used
by the CLI and never starts a browser server.
"""
from __future__ import annotations

import asyncio
import logging
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
        self._root.title(f"{self._name} — Local Assistant")
        self._root.geometry("1080x720")
        self._root.minsize(760, 520)
        self._root.configure(bg="#0b0f15")

    def _build_interface(self) -> None:
        sidebar = tk.Frame(self._root, bg="#121923", width=230)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="●  ATLAS", fg="#f6b73c", bg="#121923", font=("Helvetica", 19, "bold")).pack(
            anchor=tk.W, padx=24, pady=(30, 4)
        )
        tk.Label(sidebar, text="LOCAL PERSONAL ASSISTANT", fg="#91a0b2", bg="#121923", font=("Helvetica", 9, "bold")).pack(
            anchor=tk.W, padx=25
        )
        tk.Frame(sidebar, height=2, bg="#283342").pack(fill=tk.X, padx=24, pady=26)
        tk.Label(sidebar, text="PRIVATE SESSION", fg="#91a0b2", bg="#121923", font=("Helvetica", 9, "bold")).pack(
            anchor=tk.W, padx=25
        )
        tk.Label(sidebar, text="Your conversations\nstay on this Mac.", justify=tk.LEFT, fg="#e9edf2", bg="#121923", font=("Helvetica", 12)).pack(
            anchor=tk.W, padx=25, pady=(7, 0)
        )
        status = tk.Frame(sidebar, bg="#101722", highlightbackground="#283342", highlightthickness=1)
        status.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=24)
        tk.Label(status, text="●  READY", fg="#70db9a", bg="#101722", font=("Helvetica", 10, "bold")).pack(anchor=tk.W, padx=14, pady=(13, 3))
        tk.Label(status, text="Local model connected", fg="#a7b2bf", bg="#101722", font=("Helvetica", 10)).pack(anchor=tk.W, padx=14, pady=(0, 13))

        content = tk.Frame(self._root, bg="#0b0f15")
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(18, 24), pady=24)
        header = tk.Frame(content, bg="#151a22", highlightbackground="#2a3340", highlightthickness=1)
        header.pack(fill=tk.X)
        tk.Label(header, text="ATLAS / PRIVATE SESSION", fg="#91a0b2", bg="#151a22", font=("Helvetica", 9, "bold")).pack(anchor=tk.W, padx=24, pady=(19, 2))
        tk.Label(header, text="How can I help?", fg="#e9edf2", bg="#151a22", font=("Helvetica", 22, "bold")).pack(anchor=tk.W, padx=24)
        tk.Label(header, text="Ask naturally. Atlas uses local tools only when needed.", fg="#a7b2bf", bg="#151a22", font=("Helvetica", 11)).pack(anchor=tk.W, padx=24, pady=(2, 19))

        self._transcript = scrolledtext.ScrolledText(content, wrap=tk.WORD, state=tk.DISABLED, bg="#151a22", fg="#e9edf2", insertbackground="#e9edf2", relief=tk.FLAT, padx=24, pady=20, font=("Helvetica", 12))
        self._transcript.pack(fill=tk.BOTH, expand=True, pady=(1, 0))
        self._transcript.tag_configure("atlas", foreground="#f6b73c", font=("Helvetica", 10, "bold"))
        self._transcript.tag_configure("user", foreground="#9bc8ff", font=("Helvetica", 10, "bold"))
        self._append("Atlas", "Hello — I’m Atlas. What would you like to work on?")

        composer = tk.Frame(content, bg="#151a22", highlightbackground="#2a3340", highlightthickness=1)
        composer.pack(fill=tk.X, pady=(1, 0))
        self._input = tk.Text(composer, height=3, wrap=tk.WORD, bg="#0d1219", fg="#e9edf2", insertbackground="#e9edf2", relief=tk.FLAT, padx=12, pady=10, font=("Helvetica", 12))
        self._input.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(14, 8), pady=14)
        self._input.bind("<Command-Return>", self._send_event)
        self._input.bind("<Control-Return>", self._send_event)
        self._send_button = tk.Button(composer, text="Send", command=self._send, bg="#f6b73c", fg="#17120a", activebackground="#ffd775", relief=tk.FLAT, font=("Helvetica", 11, "bold"), padx=22, pady=12)
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


def main() -> None:
    config = AtlasConfig()
    config.ensure_directories()
    _configure_logging(config)
    root = tk.Tk()
    root.withdraw()
    splash = tk.Toplevel(root)
    splash.overrideredirect(True)
    splash.geometry("460x250")
    splash.configure(bg="#0b0f15")
    tk.Label(splash, text="●", fg="#f6b73c", bg="#0b0f15", font=("Helvetica", 30)).pack(pady=(60, 0))
    tk.Label(splash, text="ATLAS", fg="#e9edf2", bg="#0b0f15", font=("Helvetica", 26, "bold")).pack()
    tk.Label(splash, text="Starting your local assistant…", fg="#91a0b2", bg="#0b0f15", font=("Helvetica", 12)).pack(pady=(10, 0))

    def launch() -> None:
        try:
            assistant = asyncio.run(_create_assistant(config))
        except RuntimeError as exc:
            splash.destroy()
            root.deiconify()
            tk.Label(root, text=str(exc), padx=30, pady=30).pack()
            return
        splash.destroy()
        root.deiconify()
        AtlasDesktopApp(root, assistant, config.assistant_name)

    root.after(700, launch)
    root.mainloop()


if __name__ == "__main__":
    main()
