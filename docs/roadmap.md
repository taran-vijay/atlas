# Roadmap

- [x] **Milestone 0 -- Architecture.** Repository structure, interfaces,
      config system, tool architecture, voice architecture, security model.
- [ ] **Milestone 1 -- Minimum viable assistant.** Local LLM integration via
      Ollama, text in/out, conversation loop, configuration, logging, tests.
      *(scaffolded; run it against a local Ollama install to complete this milestone)*
- [ ] **Milestone 2 -- Voice.** Wake word (openWakeWord), local STT
      (faster-whisper), local TTS (Piper), voice conversation loop.
- [ ] **Milestone 3 -- Tool architecture in practice.** 2-3 real
      `READ_ONLY` tools built on the existing registry/permission framework.
- [ ] **Milestone 4 -- macOS integration.** Calendar read, notifications,
      application launching, system status -- via `PlatformIntegration`.
- [ ] **Milestone 5 -- Memory.** Long-term/semantic memory layer behind the
      existing `MemoryStore` interface; user-facing "what do you remember
      about me" / "forget that" commands.
- [ ] **Milestone 6 -- Advanced assistant.** Email integration, RAG, vision,
      scheduled actions, plugin marketplace, Windows support.

## Explicitly out of scope for now

Arbitrary shell execution as a tool, any cloud LLM as the default backend,
a mandatory server component, and Windows support before the macOS core is
stable. See the main README for the full rationale.
