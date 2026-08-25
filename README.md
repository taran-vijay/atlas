# Atlas

A local-first, privacy-focused, voice-controlled personal AI assistant.

Atlas runs on your own machine, talks to a local LLM, and keeps your data
where it belongs -- with you. No mandatory account, no mandatory server, no
subscription, and no cloud API required to use the default experience.

> **Status: early / V1 (text-only).** Voice, tools, and macOS integrations
> are designed into the architecture but not all built yet -- see
> [`docs/roadmap.md`](docs/roadmap.md) for exactly what's done vs. planned.

## Why

Most "AI assistant" projects either wrap a paid cloud API or stay a toy demo.
Atlas is built to do neither: it's a real local pipeline (wake word -> speech
recognition -> local LLM -> permission-gated tools -> speech synthesis) with
a genuinely modular architecture, so it can grow from a text chatbot into a
real voice assistant without a rewrite at each step.

## Architecture

```
User -> Wake word -> Speech-to-text -> Assistant core (local LLM)
                                              |
                                     Tool executor (permission-gated)
                                              |
                                  Local OS & data (calendar, files, apps)
                                              |
                                     Text-to-speech -> User
```

Full write-up, including why each piece is designed the way it is:
[`docs/architecture.md`](docs/architecture.md).

## Features

**Working today (V1):**
- Local LLM conversation loop via [Ollama](https://ollama.com)
- Typed configuration system (env vars / `.env`)
- Rolling conversation memory (SQLite, local file)
- Structured logging
- Tool registry + permission framework (no tools registered yet -- see roadmap)
- Unit + integration test suite

**Planned:** wake word activation, local speech-to-text/text-to-speech,
real macOS tools (calendar, notifications, app launching), long-term memory,
and more -- see [`docs/roadmap.md`](docs/roadmap.md).

## Requirements

- macOS (primary target; Windows is architected for but not implemented)
- Python 3.11+
- [Ollama](https://ollama.com) installed and running
- ~8-16GB RAM depending on the model you choose (see below)

## Quick start

```bash
git clone <your-repo-url> atlas
cd atlas
./scripts/setup.sh          # creates a venv, installs deps, pulls the default model
source .venv/bin/activate
atlas
```

`scripts/setup.sh` checks for Python and Ollama, creates `.venv`, installs
Atlas in editable mode, pulls the default model (`llama3.1:8b`), and copies
`.env.example` to `.env`. If you'd rather do it by hand:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ollama pull llama3.1:8b
cp .env.example .env
atlas
```

## Configuration

All configuration lives in environment variables (or `.env`), prefixed
`ATLAS_`. See [`.env.example`](.env.example) for the full list, including
`ATLAS_ASSISTANT_NAME`, `ATLAS_LLM_MODEL`, `ATLAS_OLLAMA_HOST`, and
`ATLAS_LOG_LEVEL`. Nothing is hardcoded elsewhere in the codebase -- every
setting flows through `atlas.core.config.schema.AtlasConfig`.

If your machine has less RAM, swap `ATLAS_LLM_MODEL` for a smaller model
(e.g. a 3B-class model) and `ollama pull` it first.

## Permissions

V1 doesn't request any macOS permissions -- it's text-only with no tools
registered. Future milestones will request Microphone, Calendar, and
Automation access as those features ship; see
[`docs/permissions.md`](docs/permissions.md) for what each one will be used
for and when.

## Security model

The LLM never executes anything directly -- every capability is an explicit
`Tool` with a declared permission tier (`READ_ONLY` / `CONFIRM` /
`PRIVILEGED`), enforced by a single registry choke point. There is no
general shell-execution tool. Full details, including how untrusted content
(emails, web pages) is kept separate from instructions, are in
[`docs/security-model.md`](docs/security-model.md).

## Troubleshooting

**"Could not reach Ollama"** -- make sure `ollama serve` is running and
you've pulled the model named in `ATLAS_LLM_MODEL` (`ollama pull
llama3.1:8b`).

**Slow responses** -- try a smaller model, or check Activity Monitor for
memory pressure; local inference on an underpowered machine is the most
common cause of latency.

## Testing

```bash
pytest
```

Unit tests cover config, the tool registry's permission enforcement, and
the assistant core in isolation (mocked LLM). Integration tests run a
scripted multi-turn conversation through the real SQLite-backed memory
store with a stubbed LLM, so they need no network access or running model.

## Contributing

This is an early-stage personal project growing milestone by milestone --
see [`docs/roadmap.md`](docs/roadmap.md) before picking something to work
on, and open an issue to discuss non-trivial changes first. Please run
`pytest`, `ruff check .`, and `mypy .` before opening a PR.

## License

[MIT](LICENSE)
