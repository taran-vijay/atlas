# A.T.L.A.S - Adaptive Learning and Technical System

Atlas is a local-first personal AI assistant for macOS. It runs its language
model through Ollama, keeps its memories and logs on your Mac, and only acts
through explicitly scoped, permission-gated tools.

> **Status: local macOS desktop assistant.** Atlas has a native desktop app,
> local memory, system/file tools, confirmation-gated actions, optional
> on-device voice output, and optional local push-to-talk voice input.
> Calendar and Mail are not implemented yet.

## What Atlas can do

- Run a native macOS desktop chat app or a terminal chat session
- Use a local Ollama model for normal conversation and writing
- Remember facts you explicitly ask it to save, locally in SQLite
- Adapt reply length and tone from aggregate, on-device communication signals;
  reset those preferences any time from **Memory Archive**
- Offer safe, clickable follow-up suggestions based on the current exchange
- Read system time, OS details, battery, processes, network, and selected
  local-file information
- Open apps/files, write to the clipboard, and perform scoped file actions
  only after your in-app confirmation
- Keep an action history and distinguish verified results from unavailable data
- Read replies aloud with a built-in macOS voice or optional local Piper
  neural voices, while keeping the visible transcript paced with speech
- Turn speech into text locally with an optional hold-to-talk control

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

## Voice input (optional)

Atlas can transcribe speech locally while you hold **HOLD TO TALK** in the
desktop app. Releasing the control sends the transcribed request directly to
Atlas; typing remains available when you prefer it. Install the local engine
and rapid command speech model once:

```bash
./scripts/setup_voice_input.sh
```

This setup uses Homebrew to install whisper.cpp, then downloads the local
English speech model. Atlas uses the compact model for responsive command
transcription and warms it in the background after launch.

The first use asks macOS for microphone permission. Recording starts only
while the control is held, stops when released, and is transcribed on-device.
Atlas never keeps listening in the background and does not send audio to a
remote service.

## Configuration

Configuration lives in `.env` or environment variables beginning with
`ATLAS_`. See [`.env.example`](.env.example). Useful settings include
`ATLAS_ASSISTANT_NAME`, `ATLAS_LLM_MODEL`, `ATLAS_OLLAMA_HOST`, and
`ATLAS_NEURAL_VOICE_MODELS_DIR`.

## Personalization and response speed

Atlas learns only a small local communication profile: whether your recent
messages tend to be concise or detailed, and casual or neutral. It uses that
profile to phrase replies more naturally. This is not a cloud profile and does
not grant Atlas new access to personal data. Reset it through **Memory Archive
→ Reset Communication Style**, or say “reset communication preferences.”

For the fastest replies, keep Ollama running and select a model that fits your
Mac's memory comfortably. Atlas keeps conversation context bounded and reuses
the loaded model between requests. Raw model speed still depends primarily on
the selected model and your Mac.

## Permissions

Atlas never bypasses macOS permission prompts. Read-only system tools need no
special permission, while every local action requires an in-app confirmation.
Calendar, Mail, and notifications are not implemented yet. Details are in
[macOS permissions](docs/permissions.md).

## Project direction

The next major layer is carefully scoped service integrations, beginning with
Calendar. See the [roadmap](docs/roadmap.md) and [architecture](docs/architecture.md).

## Development checks

```bash
source .venv/bin/activate
pytest
ruff check .
mypy .
```

## License

[MIT](LICENSE)
