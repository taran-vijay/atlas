"""Typed, validated configuration for Atlas.

Configuration is loaded from environment variables (prefixed ATLAS_) and/or
a .env file. Nothing else in the codebase should hardcode a setting -- every
subsystem that needs one receives it from an AtlasConfig instance.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMBackend(str, Enum):
    OLLAMA = "ollama"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class AtlasConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATLAS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    assistant_name: str = "Atlas"

    # LLM
    llm_backend: LLMBackend = LLMBackend.OLLAMA
    llm_model: str = "llama3.1:8b"
    ollama_host: str = "http://localhost:11434"
    llm_temperature: float = 0.4
    llm_request_timeout_seconds: float = 60.0

    # Memory
    memory_db_path: Path = Path.home() / ".atlas" / "memory.db"
    memory_max_turns: int = 20

    # Logging / audit
    log_level: LogLevel = LogLevel.INFO
    log_dir: Path = Path.home() / ".atlas" / "logs"
    audit_log_path: Path = Path.home() / ".atlas" / "logs" / "audit.log"

    def ensure_directories(self) -> None:
        """Create local data directories if they don't already exist."""
        self.memory_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
