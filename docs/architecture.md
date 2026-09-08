# Architecture

Atlas is a local macOS application with two entry points:

- `atlas` for terminal chat
- `atlas local` for the native desktop app

Both use the same `AssistantCore`, local Ollama provider, SQLite memory store,
and permission-enforcing tool registry.

## Runtime flow

```text
Desktop app or terminal chat
             |
             v
       AssistantCore
        /     |      \
       v      v       v
  Ollama   Memory   ToolRegistry
  (local)  (SQLite)      |
                     local tools
                         |
             confirmation + verification for actions
                         |
                optional local voice output
```

The desktop app checks the local Ollama connection before it opens. Voice
output is optional and uses a macOS system voice or a local Piper neural
model. Optional voice input records only while the user holds the desktop
control, then passes a local WAV file to whisper.cpp. No reply text or audio
is sent to an external speech service.

## Repository layout

```text
atlas/
  atlas/
    app.py                 # native macOS desktop app
    cli.py                 # terminal chat and `atlas local` command
    core/
      assistant/           # conversation and tool orchestration
      config/              # typed configuration
      llm/                 # Ollama provider and LLM interface
      memory/              # local SQLite history, memories, actions, settings
      tools/               # schemas, safety registry, system and action tools
      voice/               # macOS and Piper speech output
      security/            # append-only audit logger interface
  docs/
  scripts/
  tests/
```

## Tool boundary

The LLM cannot run commands directly. It may request a registered tool, but
`ToolRegistry.dispatch()` is the only execution path. The registry validates
arguments, checks the tool's permission tier, requests approval for actions,
contains implementation failures, verifies completion where possible, and
records confirmation-gated action outcomes.

Tool results are structured. The assistant only uses successful results from
the current request for machine-state claims; unavailable results are reported
as unavailable instead of being guessed.

## Data storage

Atlas stores conversation turns, explicit saved memories, action history, and
voice preferences in a local SQLite database under `~/.atlas`. Logs are also
local. Neural voice models live under `~/.atlas/voices` by default.

## Next boundary

Wake-word detection remains intentionally separate from push-to-talk speech
input. Transcribed text feeds into the same `AssistantCore` rather than
bypassing the safety, memory, or tool layers.
