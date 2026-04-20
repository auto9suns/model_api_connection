"""Error messaging when an API key is not in the environment."""

import pytest

import model_connector


def test_missing_key_error_mentions_llm_sync_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    llm = model_connector.LLMConnector()

    with pytest.raises(EnvironmentError) as excinfo:
        llm.chat("hi", provider="openai")

    msg = str(excinfo.value)
    assert "OPENAI_API_KEY" in msg
    assert "llm-sync-keys" in msg
