"""Text-in / text-out entry point for Atlas (Milestone 1).

Voice is not wired up yet -- this is the thin vertical slice that proves
config -> LLMProvider -> AssistantCore -> logging works end to end before
anything voice- or tool-related is layered on top.
"""
from __future__ import annotations

import asyncio
import logging
import sys

from atlas.core.assistant.core import AssistantCore
from atlas.core.config.schema import AtlasConfig
from atlas.core.llm.ollama_provider import OllamaProvider
from atlas.core.memory.sqlite_store import SQLiteMemoryStore
from atlas.core.tools.registry import ToolRegistry


def _configure_logging(config: AtlasConfig) -> None:
    config.log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=config.log_level.value,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(config.log_dir / "atlas.log"),
            logging.StreamHandler(sys.stderr),
        ],
    )


async def _run(config: AtlasConfig) -> None:
    logger = logging.getLogger("atlas.cli")
    config.ensure_directories()

    llm = OllamaProvider(
        host=config.ollama_host,
        model=config.llm_model,
        temperature=config.llm_temperature,
        timeout=config.llm_request_timeout_seconds,
    )
    if not await llm.is_available():
        print(
            f"Could not reach Ollama at {config.ollama_host}. "
            f"Is it running (`ollama serve`) with the '{config.llm_model}' model pulled?",
            file=sys.stderr,
        )
        raise SystemExit(1)

    memory = SQLiteMemoryStore(config.memory_db_path)
    tools = ToolRegistry()  # empty in V1 -- framework only, see docs/roadmap.md
    assistant = AssistantCore(
        assistant_name=config.assistant_name,
        llm=llm,
        memory=memory,
        tools=tools,
        max_history_turns=config.memory_max_turns,
    )

    print(f"{config.assistant_name} is ready. Type 'exit' to quit.")
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            break

        logger.info("user_message_received length=%d", len(user_input))
        reply = await assistant.handle_message(user_input)
        print(f"{config.assistant_name}> {reply}")


def main() -> None:
    config = AtlasConfig()
    _configure_logging(config)
    asyncio.run(_run(config))


if __name__ == "__main__":
    main()
