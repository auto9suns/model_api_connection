"""Unit tests for model_connector — no real API calls needed."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from model_connector import LLMConnector, strip_think_stream


# ── Fixtures ───────────────────────────────────────────────────────────────────

SAMPLE_CONFIG = {
    "providers": {
        "openai": {
            "type": "openai",
            "api_key_env": "OPENAI_API_KEY",
            "default_model": "gpt-4o",
            "models": {"gpt-4o": "gpt-4o", "gpt-4o-mini": "gpt-4o-mini"},
        },
        "anthropic": {
            "type": "anthropic",
            "api_key_env": "ANTHROPIC_API_KEY",
            "default_model": "sonnet-4.6",
            "models": {"sonnet-4.6": "claude-sonnet-4-6"},
        },
        "siliconflow": {
            "type": "openai_compatible",
            "api_key_env": "SILICONFLOW_API_KEY",
            "base_url": "https://api.siliconflow.cn/v1",
            "default_model": "deepseek-v3",
            "models": {"deepseek-v3": "deepseek-ai/DeepSeek-V3"},
        },
    }
}


@pytest.fixture
def config_file(tmp_path):
    p = tmp_path / "models_config.json"
    p.write_text(json.dumps(SAMPLE_CONFIG))
    return p


@pytest.fixture
def connector(config_file):
    return LLMConnector(
        config_path=config_file,
        api_keys={"openai": "sk-test", "anthropic": "sk-ant-test", "siliconflow": "sf-test"},
    )


# ── Config & metadata tests ───────────────────────────────────────────────────

def test_list_providers(connector):
    assert set(connector.list_providers()) == {"openai", "anthropic", "siliconflow"}


def test_list_models(connector):
    assert connector.list_models("openai") == ["gpt-4o", "gpt-4o-mini"]


def test_default_model(connector):
    assert connector.default_model("openai") == "gpt-4o"
    assert connector.default_model("anthropic") == "sonnet-4.6"


def test_unknown_provider(connector):
    with pytest.raises(ValueError, match="Unknown provider"):
        connector.chat("hi", provider="nonexistent")


# ── Model resolution tests ────────────────────────────────────────────────────

def test_resolve_known_model(connector):
    prov_cfg = connector._get_provider_config("siliconflow")
    assert connector._resolve_model(prov_cfg, "deepseek-v3") == "deepseek-ai/DeepSeek-V3"


def test_resolve_unknown_model_passthrough(connector):
    prov_cfg = connector._get_provider_config("openai")
    assert connector._resolve_model(prov_cfg, "gpt-5-turbo") == "gpt-5-turbo"


def test_resolve_default_model(connector):
    prov_cfg = connector._get_provider_config("openai")
    assert connector._resolve_model(prov_cfg, None) == "gpt-4o"


# ── API key resolution tests ──────────────────────────────────────────────────

def test_api_key_from_override(connector):
    prov_cfg = connector._get_provider_config("openai")
    assert connector._get_api_key("openai", prov_cfg) == "sk-test"


def test_api_key_from_env(config_file, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    llm = LLMConnector(config_path=config_file)
    prov_cfg = llm._get_provider_config("openai")
    assert llm._get_api_key("openai", prov_cfg) == "sk-from-env"


def test_api_key_missing(config_file, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    llm = LLMConnector(config_path=config_file)
    prov_cfg = llm._get_provider_config("openai")
    with pytest.raises(EnvironmentError, match="API key"):
        llm._get_api_key("openai", prov_cfg)


# ── Chat message normalization ─────────────────────────────────────────────────

def test_string_message_wrapped(connector):
    """A plain string should be wrapped into [{"role": "user", "content": ...}]."""
    with patch.object(connector, "_get_client") as mock_get:
        mock_client = MagicMock()
        mock_client.chat.return_value = "Hello!"
        mock_get.return_value = mock_client

        connector.chat("Hi", provider="openai")

        mock_client.chat.assert_called_once()
        msgs = mock_client.chat.call_args[0][0]
        assert msgs == [{"role": "user", "content": "Hi"}]


# ── strip_think_stream tests ──────────────────────────────────────────────────

def test_strip_think_no_tags():
    chunks = ["Hello", " world"]
    result = "".join(strip_think_stream(iter(chunks)))
    assert result == "Hello world"


def test_strip_think_removes_reasoning():
    chunks = ["<think>", "reasoning here", "</think>", "Final answer"]
    result = "".join(strip_think_stream(iter(chunks)))
    assert result == "Final answer"


def test_strip_think_partial_tags():
    """Tags split across chunks should still be handled."""
    chunks = ["<thi", "nk>thinking</th", "ink>answer"]
    result = "".join(strip_think_stream(iter(chunks)))
    assert result == "answer"


def test_strip_think_preserves_content_around_tags():
    chunks = ["Before<think>hidden</think>After"]
    result = "".join(strip_think_stream(iter(chunks)))
    assert result == "BeforeAfter"
