from typing import Any

from atlas.core.config.schema import AtlasConfig, LLMBackend


def test_defaults_are_sensible() -> None:
    config = AtlasConfig()
    assert config.assistant_name == "Atlas"
    assert config.llm_backend == LLMBackend.OLLAMA
    assert config.memory_max_turns > 0


def test_env_prefix_overrides(monkeypatch: Any) -> None:
    monkeypatch.setenv("ATLAS_ASSISTANT_NAME", "TestBot")
    config = AtlasConfig()
    assert config.assistant_name == "TestBot"
