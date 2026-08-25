# Architecture

## Repository layout

```
atlas/
  atlas/
    cli.py                 # V1 entry point: text-in/text-out loop
    core/
      config/               # typed settings (pydantic-settings)
      llm/                  # LLMProvider interface + OllamaProvider
      tools/                # Tool base class + permission-enforcing registry
      memory/               # MemoryStore interface + SQLite implementation
      assistant/            # AssistantCore orchestration loop
      voice/                # WakeWordDetector / SpeechRecognizer / SpeechSynthesizer interfaces
      security/             # AuditLogger
    platforms/
      base.py                # PlatformIntegration interface
      macos/                 # macOS implementation (Milestone 4, not yet built)
      windows/                # placeholder only
  tests/
    unit/
    integration/
  docs/
  scripts/
```

Every subsystem core code depends on is an abstract interface
(`LLMProvider`, `Tool`, `MemoryStore`, `WakeWordDetector`, `SpeechRecognizer`,
`SpeechSynthesizer`, `PlatformIntegration`). Concrete implementations are
swapped in via configuration, never imported directly by orchestration code.
This is what makes "replace the LLM" or "add Windows support" a matter of
writing a new implementation of an existing interface, not a rewrite.

## Data flow (target architecture, voice added in Milestone 2)

```
User
  |
  v
Wake word detector  (on-device, always listening)
  |
  v
Speech-to-text      (local, e.g. faster-whisper)
  |
  v
Assistant core  <---------------------+
  |  (local LLM decides response      |
  |   and/or which tool to call)      |
  v                                   |
Tool executor  (permission-gated) ----+
  |
  v
Local OS & data  (calendar, mail, files, apps -- read via platform integration)
  |
  v
Text-to-speech      (local, e.g. Piper)
  |
  v
User
```

In V1 (current state), there is no voice and no tools yet -- the flow is
just `user text -> Assistant core -> local LLM -> reply text`, with an empty
`ToolRegistry` wired in so the orchestration boundary already exists.

## Why this shape

- **No component silently escalates.** The LLM proposes a tool call; it
  never executes anything. `ToolRegistry.dispatch()` is the only path from
  a tool call to real system access, and it enforces permissions on every
  call, not just the ones a developer remembers to check.
- **Everything the LLM depends on is replaceable.** `LLMProvider`,
  `MemoryStore`, and the voice interfaces are all things `AssistantCore`
  is written against, not concrete classes -- see `docs/roadmap.md` for
  what's expected to change first.
- **Platform code stays out of core.** `atlas/core` never imports
  `atlas/platforms`. Only tool implementations (added in Milestone 4)
  will depend on a `PlatformIntegration`, keeping the orchestration loop
  identical across macOS and (eventually) Windows.

See `docs/security-model.md` for the permission and prompt-injection model,
and `docs/roadmap.md` for what's built vs. planned.
