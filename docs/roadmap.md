# Roadmap

## Completed foundations

- [x] **Local assistant core.** Ollama conversation, typed configuration,
  logging, tests, terminal chat, and a native macOS desktop app.
- [x] **Tool reliability and safety.** Structured results, argument
  validation, read-only retries, result verification, and protection against
  invented or stale tool data.
- [x] **macOS local tools.** System status, file inspection/search, and
  confirmation-gated local actions such as opening apps/files, clipboard
  writes, and scoped file operations.
- [x] **Memory v0.1.** Local conversation history, explicit long-term saved
  memories, and a local action history.
- [x] **Voice output v0.3.** Configurable macOS speech, optional local Piper
  neural voices, synchronized reply text, and a startup announcement.

## Next

- [ ] **Voice input.** On-device wake word detection and speech-to-text, with
  microphone permission requested only when the user enables it.
- [ ] **Service integrations.** Calendar, Reminders, Mail, notifications, and
  other integrations with explicit scopes and capability-aware replies.
- [ ] **Desktop refinement.** Better settings, update handling, packaging, and
  a smoother first-run experience.
- [ ] **Advanced local assistance.** Better long-term retrieval, optional RAG,
  scheduled actions, and vision—each behind a clear privacy and permission
  boundary.
- [ ] **Platform expansion.** Windows after the macOS core is stable.

## Explicitly out of scope for now

Arbitrary shell execution, a cloud LLM as the default backend, and silent
access to private services or data. Atlas remains local-first and asks before
it changes your computer.
