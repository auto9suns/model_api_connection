"""Tests for model_connector's auto-loading of ~/.config/llm/keys.env."""

import importlib
import os


def test_import_calls_load_dotenv_with_keys_env_path(tmp_path, monkeypatch):
    fake_keys_env = tmp_path / "keys.env"
    fake_keys_env.write_text("OPENAI_API_KEY=sk-from-cache\n", encoding="utf-8")

    monkeypatch.setattr("paths.KEYS_ENV_PATH", fake_keys_env, raising=True)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    import model_connector

    importlib.reload(model_connector)

    assert os.environ.get("OPENAI_API_KEY") == "sk-from-cache"


def test_import_does_not_override_existing_env_var(tmp_path, monkeypatch):
    fake_keys_env = tmp_path / "keys.env"
    fake_keys_env.write_text("OPENAI_API_KEY=sk-from-cache\n", encoding="utf-8")

    monkeypatch.setattr("paths.KEYS_ENV_PATH", fake_keys_env, raising=True)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-shell")

    import model_connector

    importlib.reload(model_connector)

    assert os.environ["OPENAI_API_KEY"] == "sk-from-shell"


def test_import_survives_missing_keys_env(tmp_path, monkeypatch):
    missing = tmp_path / "nope.env"
    monkeypatch.setattr("paths.KEYS_ENV_PATH", missing, raising=True)

    import model_connector

    importlib.reload(model_connector)  # should not raise
