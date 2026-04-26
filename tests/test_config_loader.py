"""Tests for model_connector.config — LLMConfig dataclass and parse_llm_config."""

import json

import pytest
from model_connector.config import LLMConfig, load_llm_config, parse_llm_config


# ── parse_llm_config: happy path ──────────────────────────────────────────────

def test_parse_minimal():
    """Minimal valid dict returns correct LLMConfig with empty extra."""
    cfg = parse_llm_config({"provider": "siliconflow", "model": "kimi-k2.5"})
    assert cfg.provider == "siliconflow"
    assert cfg.model == "kimi-k2.5"
    assert cfg.extra == {}


def test_parse_extra_fields_preserved():
    """All non-provider/model fields are kept verbatim in extra."""
    cfg = parse_llm_config({
        "provider": "poe",
        "model": "claude-haiku-4.5",
        "secondary_provider": "siliconflow",
        "secondary_model": "kimi-k2.5",
        "max_tokens": 512,
        "timeout": 30,
    })
    assert cfg.provider == "poe"
    assert cfg.model == "claude-haiku-4.5"
    assert cfg.extra["secondary_provider"] == "siliconflow"
    assert cfg.extra["secondary_model"] == "kimi-k2.5"
    assert cfg.extra["max_tokens"] == 512
    assert cfg.extra["timeout"] == 30


# ── parse_llm_config: validation errors ──────────────────────────────────────

def test_parse_missing_provider():
    with pytest.raises(ValueError, match="missing required field: provider"):
        parse_llm_config({"model": "kimi-k2.5"})


def test_parse_missing_model():
    with pytest.raises(ValueError, match="missing required field: model"):
        parse_llm_config({"provider": "siliconflow"})


def test_parse_provider_empty_string():
    with pytest.raises(ValueError, match="non-empty string"):
        parse_llm_config({"provider": "", "model": "kimi-k2.5"})


def test_parse_model_empty_string():
    with pytest.raises(ValueError, match="non-empty string"):
        parse_llm_config({"provider": "siliconflow", "model": ""})


def test_parse_provider_non_string():
    with pytest.raises(ValueError, match="non-empty string"):
        parse_llm_config({"provider": 42, "model": "kimi-k2.5"})


def test_parse_model_non_string():
    with pytest.raises(ValueError, match="non-empty string"):
        parse_llm_config({"provider": "siliconflow", "model": None})


# ── LLMConfig immutability ────────────────────────────────────────────────────

def test_llmconfig_is_frozen():
    cfg = parse_llm_config({"provider": "anthropic", "model": "claude-sonnet-4.6"})
    with pytest.raises(AttributeError):  # FrozenInstanceError is a subclass of AttributeError
        cfg.provider = "openai"  # type: ignore


# ── load_llm_config ───────────────────────────────────────────────────────────


def test_load_valid_file(tmp_path):
    """Valid llm.json returns correct LLMConfig."""
    f = tmp_path / "llm.json"
    f.write_text(json.dumps({"provider": "siliconflow", "model": "kimi-k2.5"}))
    cfg = load_llm_config(f)
    assert cfg.provider == "siliconflow"
    assert cfg.model == "kimi-k2.5"


def test_load_valid_file_with_extras(tmp_path):
    """Extra fields are preserved in LLMConfig.extra."""
    f = tmp_path / "llm.json"
    f.write_text(json.dumps({
        "provider": "poe",
        "model": "claude-haiku-4.5",
        "secondary_provider": "siliconflow",
        "secondary_model": "kimi-k2.5",
        "max_tokens": 512,
        "timeout": 30,
    }))
    cfg = load_llm_config(f)
    assert cfg.extra["max_tokens"] == 512
    assert cfg.extra["secondary_provider"] == "siliconflow"


def test_load_missing_file(tmp_path):
    """FileNotFoundError raised when file does not exist; message contains path."""
    missing = tmp_path / "llm.json"
    with pytest.raises(FileNotFoundError, match=str(missing)):
        load_llm_config(missing)


def test_load_invalid_json(tmp_path):
    """json.JSONDecodeError raised on malformed JSON."""
    f = tmp_path / "llm.json"
    f.write_text("{ not valid json }")
    with pytest.raises(json.JSONDecodeError):
        load_llm_config(f)


def test_load_missing_provider(tmp_path):
    """ValueError raised when provider field is absent."""
    f = tmp_path / "llm.json"
    f.write_text(json.dumps({"model": "kimi-k2.5"}))
    with pytest.raises(ValueError, match="missing required field: provider"):
        load_llm_config(f)
