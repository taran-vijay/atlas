from atlas.core.config.schema import AtlasConfig, LLMBackend


def test_defaults_are_sensible():
    config = AtlasConfig(_env_file=None)
    assert config.assistant_name == "Atlas"
    assert config.llm_backend == LLMBackend.OLLAMA
    assert config.memory_max_turns > 0


def test_env_prefix_overrides(monkeypatch):
    monkeypatch.setenv("ATLAS_ASSISTANT_NAME", "TestBot")
    config = AtlasConfig(_env_file=None)
    assert config.assistant_name == "TestBot"
