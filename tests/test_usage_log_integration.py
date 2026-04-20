"""Integration test: importing model_connector triggers usage_log.register()."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_import_model_connector_registers_callbacks(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    import importlib
    import litellm
    litellm.success_callback = []
    litellm.failure_callback = []

    import usage_log
    importlib.reload(usage_log)
    import model_connector
    importlib.reload(model_connector)

    assert usage_log._log_success in litellm.success_callback
    assert usage_log._log_failure in litellm.failure_callback


def test_chat_provider_passes_through_to_metadata(monkeypatch, tmp_path):
    """chat() must put the provider key into litellm metadata so the callback can record it."""
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    import importlib
    import usage_log
    importlib.reload(usage_log)

    import model_connector
    importlib.reload(model_connector)

    from unittest.mock import MagicMock, patch
    import json as _json

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "ok"

    config = {"providers": {"openai": {
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o",
        "models": {"gpt-4o": "openai/gpt-4o"},
    }}}
    cfg = tmp_path / "models_config.json"
    cfg.write_text(_json.dumps(config))

    llm = model_connector.LLMConnector(config_path=cfg, api_keys={"openai": "sk-test"})

    with patch("model_connector.litellm.completion", return_value=mock_response) as mock_comp:
        llm.chat("hi", provider="openai")
        call_kwargs = mock_comp.call_args[1]
        meta = (call_kwargs.get("metadata") or {})
        assert meta.get("provider") == "openai"
