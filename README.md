# Atlas

Atlas is a local-first personal AI assistant for macOS. It runs its language
model through Ollama, keeps its memories and logs on your Mac, and only acts
through explicitly scoped, permission-gated tools.

> **Status: local macOS desktop assistant.** Atlas has a native desktop app,
> local memory, system/file tools, confirmation-gated actions, and optional
> on-device voice output. Voice input and integrations such as Calendar and
> Mail are not implemented yet.

## What Atlas can do

- Run a native macOS desktop chat app or a terminal chat session
- Use a local Ollama model for normal conversation and writing
- Remember facts you explicitly ask it to save, locally in SQLite
- Read system time, OS details, battery, processes, network, and selected
  local-file information
- Open apps/files, write to the clipboard, and perform scoped file actions
  only after your in-app confirmation
- Keep an action history and distinguish verified results from unavailable data
- Read replies aloud with a built-in macOS voice or optional local Piper
  neural voices

Atlas cannot yet read Calendar, Mail, Messages, reminders, browser data, or
other connected services. It says so directly instead of inventing results.

## Privacy and safety

Atlas has no mandatory account, cloud API, or server. The local model does not
execute shell commands directly: every capability is an individual tool with a
permission tier. Read-only tools run only for explicit computer/file requests;
actions always ask for approval first. See [the security model](docs/security-model.md).

## Requirements

- macOS
- Python 3.11 or newer
- [Ollama](https://ollama.com) installed
- Around 8–16 GB RAM, depending on your selected local model

## Setup and launch

Clone Atlas, enter the project folder, and run setup once:

```bash
git clone <your-repo-url> atlas
cd atlas
./scripts/setup.sh
```

Setup creates Atlas's local environment, installs its dependencies, pulls the
default Ollama model, creates `.env` if needed, and installs a safe launcher.
Open a new Terminal and run:

```bash
atlas local
```

That starts the desktop app. Use `atlas` alone for terminal chat. If another
app already owns the `atlas` command, setup deliberately leaves it alone; from
the project folder, use:

```bash
source .venv/bin/activate
atlas local
```

## Neural voice (optional)

Atlas starts with macOS speech as a fallback. To install its five local Piper
neural voice models—three male and two female—run:

```bash
./scripts/setup_neural_voice.sh
```

Restart with `atlas local`, then choose **Settings → Voice → Local Neural**.
The models and generated audio stay on your Mac. Set
`ATLAS_NEURAL_VOICE_MODELS_DIR` in `.env` to use a different compatible Piper
model directory.

## Configuration

Configuration lives in `.env` or environment variables beginning with
`ATLAS_`. See [`.env.example`](.env.example). Useful settings include
`ATLAS_ASSISTANT_NAME`, `ATLAS_LLM_MODEL`, `ATLAS_OLLAMA_HOST`, and
`ATLAS_NEURAL_VOICE_MODELS_DIR`.

## Permissions

Atlas never bypasses macOS permission prompts. Read-only system tools need no
special permission, while every local action requires an in-app confirmation.
Calendar, Mail, notifications, microphone access, and voice input are not
implemented yet. Details are in [macOS permissions](docs/permissions.md).

## Project direction

The next major layer is local voice input—wake word detection and
speech-to-text—followed by carefully scoped service integrations. See the
[roadmap](docs/roadmap.md) and [architecture](docs/architecture.md).

## Development checks

```bash
source .venv/bin/activate
pytest
ruff check .
mypy .
```

## License

[MIT](LICENSE)
