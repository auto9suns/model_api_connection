"""Unit tests for model_connector — no real API calls needed."""

import json
from unittest.mock import MagicMock, patch

import pytest

from model_connector import LLMConnector, strip_think_stream


# ── Fixtures ───────────────────────────────────────────────────────────────────

SAMPLE_CONFIG = {
    "providers": {
        "openai": {
            "api_key_env": "OPENAI_API_KEY",
            "default_model": "gpt-4o",
            "models": {"gpt-4o": "openai/gpt-4o", "gpt-4o-mini": "openai/gpt-4o-mini"},
        },
        "anthropic": {
            "api_key_env": "ANTHROPIC_API_KEY",
            "default_model": "sonnet-4.6",
            "models": {"sonnet-4.6": "anthropic/claude-sonnet-4-6"},
        },
        "siliconflow": {
            "api_key_env": "SILICONFLOW_API_KEY",
            "base_url": "https://api.siliconflow.cn/v1",
            "default_model": "deepseek-v3",
            "models": {"deepseek-v3": "openai/deepseek-ai/DeepSeek-V3"},
        },
        "poe": {
            "api_key_env": "POE_API_KEY",
            "default_model": "GPT-4o",
            "models": {"GPT-4o": "poe/GPT-4o"},
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
        api_keys={
            "openai": "sk-test",
            "anthropic": "sk-ant-test",
            "siliconflow": "sf-test",
            "poe": "poe-test",
        },
    )


# ── Config & metadata tests ───────────────────────────────────────────────────

def test_list_providers(connector):
    assert set(connector.list_providers()) == {"openai", "anthropic", "siliconflow", "poe"}


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
    assert connector._resolve_model(prov_cfg, "deepseek-v3") == "openai/deepseek-ai/DeepSeek-V3"


def test_resolve_unknown_model_passthrough(connector):
    prov_cfg = connector._get_provider_config("openai")
    assert connector._resolve_model(prov_cfg, "gpt-5-turbo") == "gpt-5-turbo"


def test_resolve_default_model(connector):
    prov_cfg = connector._get_provider_config("openai")
    assert connector._resolve_model(prov_cfg, None) == "openai/gpt-4o"


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


# ── Chat call tests ───────────────────────────────────────────────────────────

def test_string_message_wrapped(connector):
    """A plain string should be wrapped into [{"role": "user", "content": ...}]."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Hello!"

    with patch("model_connector.litellm.completion", return_value=mock_response) as mock_comp:
        result = connector.chat("Hi", provider="openai")

        mock_comp.assert_called_once()
        call_kwargs = mock_comp.call_args[1]
        assert call_kwargs["messages"] == [{"role": "user", "content": "Hi"}]
        assert call_kwargs["model"] == "openai/gpt-4o"
        assert call_kwargs["api_key"] == "sk-test"
        assert result == "Hello!"


def test_chat_passes_api_base_for_custom_provider(connector):
    """Providers with base_url should forward it as api_base to litellm."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "ok"

    with patch("model_connector.litellm.completion", return_value=mock_response) as mock_comp:
        connector.chat("Hi", provider="siliconflow", model="deepseek-v3")

        call_kwargs = mock_comp.call_args[1]
        assert call_kwargs["api_base"] == "https://api.siliconflow.cn/v1"
        assert call_kwargs["model"] == "openai/deepseek-ai/DeepSeek-V3"


def test_chat_with_tools(connector):
    """Function calling / tool use parameters should be forwarded to litellm."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = None
    mock_response.choices[0].message.tool_calls = [MagicMock()]

    tools = [{"type": "function", "function": {
        "name": "get_weather",
        "description": "Get weather",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
    }}]

    with patch("model_connector.litellm.completion", return_value=mock_response) as mock_comp:
        connector.chat("北京天气", provider="openai", tools=tools)

        call_kwargs = mock_comp.call_args[1]
        assert call_kwargs["tools"] == tools


def test_chat_streaming(connector):
    """Streaming should return an iterator of text chunks."""
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta.content = "Hello"

    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta.content = " world"

    mock_response = iter([chunk1, chunk2])

    with patch("model_connector.litellm.completion", return_value=mock_response):
        result = list(connector.chat("Hi", provider="openai", stream=True))
        assert result == ["Hello", " world"]


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


def test_strip_think_multiple_blocks():
    chunks = ["A<think>x</think>B<think>y</think>C"]
    result = "".join(strip_think_stream(iter(chunks)))
    assert result == "ABC"


def test_strip_think_unclosed_block():
    """An unclosed <think> block at stream end should be discarded."""
    chunks = ["answer<think>partial reasoning"]
    result = "".join(strip_think_stream(iter(chunks)))
    assert result == "answer"


def test_default_config_path_resolves():
    """models_config.json must exist next to the installed module (editable or not)."""
    import model_connector as mc
    from pathlib import Path
    config = Path(mc.__file__).parent / "models_config.json"
    assert config.exists(), f"models_config.json not found at {config}"
