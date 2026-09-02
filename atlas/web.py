"""Local web dashboard for Atlas.

The dashboard deliberately binds to loopback only. It is a second interface
for the same local assistant core used by the terminal application, not a
separate service or a remote API.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol

from atlas.cli import _build_tool_registry, _configure_logging
from atlas.core.assistant.core import AssistantCore
from atlas.core.config.schema import AtlasConfig
from atlas.core.llm.ollama_provider import OllamaProvider
from atlas.core.memory.sqlite_store import SQLiteMemoryStore

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Atlas — Local Assistant</title><style>
:root { color-scheme: dark; --ink:#e9edf2; --muted:#96a1b0; --panel:#151a22; --edge:#2a3340; --canvas:#0b0f15; --accent:#f6b73c; --user:#25364e; }
* { box-sizing:border-box } body { margin:0; min-height:100vh; background:radial-gradient(circle at 90% 0%,#202a36 0,transparent 32rem),var(--canvas); color:var(--ink); font:15px/1.55 ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
main { width:min(1100px,calc(100% - 32px)); min-height:100vh; margin:auto; display:grid; grid-template-columns:260px 1fr; gap:24px; padding:24px 0; }
aside,section { background:color-mix(in srgb,var(--panel) 92%,transparent); border:1px solid var(--edge); border-radius:18px; }
aside { padding:24px; display:flex; flex-direction:column; gap:26px; } .mark { display:flex; align-items:center; gap:11px; font-weight:700; font-size:20px; letter-spacing:.02em; } .orb { width:14px; height:14px; border-radius:50%; background:var(--accent); box-shadow:0 0 18px #f6b73c; }
.eyebrow { color:var(--muted); font-size:11px; letter-spacing:.12em; text-transform:uppercase; } .status { margin-top:auto; padding:14px; border-radius:12px; background:#101722; border:1px solid #263346; } .status b { display:block; margin:3px 0; color:#d8e8ff; } .dot { color:#70db9a; }
section { min-height:calc(100vh - 48px); display:flex; flex-direction:column; overflow:hidden; } header { padding:25px 28px 18px; border-bottom:1px solid var(--edge); } h1 { margin:2px 0 3px; font-size:22px; } header p { color:var(--muted); margin:0; }
#messages { flex:1; padding:28px; overflow-y:auto; display:flex; flex-direction:column; gap:16px; } .message { max-width:min(78%,680px); padding:14px 16px; border:1px solid var(--edge); background:#10151d; border-radius:6px 16px 16px 16px; white-space:pre-wrap; } .message.user { align-self:flex-end; background:var(--user); border-radius:16px 6px 16px 16px; } .label { font-size:11px; text-transform:uppercase; letter-spacing:.08em; color:var(--muted); margin-bottom:5px; }
form { display:flex; gap:10px; padding:18px 24px 24px; border-top:1px solid var(--edge); } textarea { flex:1; min-height:48px; max-height:160px; padding:13px; resize:vertical; color:var(--ink); font:inherit; background:#0d1219; border:1px solid var(--edge); border-radius:12px; outline:none; } textarea:focus { border-color:var(--accent); } button { min-width:92px; padding:0 18px; border:0; border-radius:12px; cursor:pointer; font:600 14px inherit; background:var(--accent); color:#16120a; } button:disabled { opacity:.55; cursor:wait; }
@media(max-width:700px) { main { display:block; padding:0; width:100%; } aside { display:none } section { min-height:100vh; border-radius:0; border:0; } #messages { padding:20px; } form { padding:14px; } }
</style></head><body><main><aside><div><div class="mark"><span class="orb"></span> Atlas</div><p class="eyebrow">Personal AI assistant</p></div><div><p class="eyebrow">Interface</p><b>Local dashboard</b><p style="color:var(--muted);margin-top:5px">Your conversations and tools stay on this Mac.</p></div><div class="status"><span class="dot">●</span> <span class="eyebrow">Status</span><b>Ready to assist</b><span style="color:var(--muted)">Connected to local Ollama</span></div></aside><section><header><div class="eyebrow">Atlas / Private session</div><h1>How can I help?</h1><p>Ask naturally. Atlas uses your computer tools only when needed.</p></header><div id="messages"><div class="message"><div class="label">Atlas</div>Hello — I’m Atlas. What would you like to work on?</div></div><form id="chat"><textarea id="prompt" aria-label="Message Atlas" placeholder="Message Atlas" required></textarea><button id="send" type="submit">Send</button></form></section></main><script>
const form=document.querySelector('#chat'), input=document.querySelector('#prompt'), messages=document.querySelector('#messages'), send=document.querySelector('#send');
function add(role,text){const item=document.createElement('div');item.className='message '+(role==='You'?'user':'');item.innerHTML='<div class="label">'+role+'</div>';const body=document.createElement('div');body.textContent=text;item.append(body);messages.append(item);messages.scrollTop=messages.scrollHeight;}
form.addEventListener('submit',async event=>{event.preventDefault();const text=input.value.trim();if(!text)return;add('You',text);input.value='';send.disabled=true;send.textContent='Thinking…';try{const response=await fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text})});const data=await response.json();if(!response.ok)throw new Error(data.error||'Atlas could not respond.');add('Atlas',data.reply);}catch(error){add('Atlas','I hit a local connection problem: '+error.message);}finally{send.disabled=false;send.textContent='Send';input.focus();}});
input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();form.requestSubmit();}});
</script></body></html>"""


class HandlesMessage(Protocol):
    async def handle_message(self, user_input: str) -> str: ...


class AtlasWebApp:
    def __init__(self, assistant: HandlesMessage) -> None:
        self._assistant = assistant
        self._lock = threading.Lock()

    def chat(self, message: str) -> str:
        """Run one request at a time so local memory turns remain ordered."""
        with self._lock:
            return asyncio.run(self._assistant.handle_message(message))


def _make_handler(app: AtlasWebApp) -> type[BaseHTTPRequestHandler]:
    class AtlasRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != "/":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            body = _PAGE.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if self.path != "/api/chat":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload: Any = json.loads(self.rfile.read(length))
                message = payload.get("message") if isinstance(payload, dict) else None
                if not isinstance(message, str) or not message.strip():
                    raise ValueError("'message' must be a non-empty string")
                if len(message) > 10_000:
                    raise ValueError("'message' must be at most 10,000 characters")
                response = {"reply": app.chat(message.strip())}
                status = HTTPStatus.OK
            except (ValueError, json.JSONDecodeError) as exc:
                response = {"error": str(exc)}
                status = HTTPStatus.BAD_REQUEST
            except Exception:
                logging.getLogger("atlas.web").exception("chat request failed")
                response = {"error": "Atlas could not complete that request."}
                status = HTTPStatus.INTERNAL_SERVER_ERROR
            body = json.dumps(response).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            logging.getLogger("atlas.web").info(format, *args)

    return AtlasRequestHandler


async def _create_app(config: AtlasConfig) -> AtlasWebApp:
    llm = OllamaProvider(
        host=config.ollama_host,
        model=config.llm_model,
        temperature=config.llm_temperature,
        timeout=config.llm_request_timeout_seconds,
    )
    if not await llm.is_available():
        raise RuntimeError(f"Could not reach Ollama at {config.ollama_host}.")
    return AtlasWebApp(
        AssistantCore(
            assistant_name=config.assistant_name,
            llm=llm,
            memory=SQLiteMemoryStore(config.memory_db_path),
            tools=_build_tool_registry(),
            max_history_turns=config.memory_max_turns,
        )
    )


def main() -> None:
    config = AtlasConfig()
    config.ensure_directories()
    _configure_logging(config)
    try:
        app = asyncio.run(_create_app(config))
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    server = ThreadingHTTPServer(("127.0.0.1", 8765), _make_handler(app))
    print("Atlas dashboard is ready at http://127.0.0.1:8765")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
