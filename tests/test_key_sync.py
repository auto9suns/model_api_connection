"""Tests for key_sync module."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from key_sync import load_providers, fetch_key, OpError, write_keys_env


def test_load_providers_returns_provider_with_op_reference(tmp_path):
    cfg = {
        "providers": {
            "openai": {
                "api_key_env": "OPENAI_API_KEY",
                "op_reference": "op://llmkeys/OpenAI/credential",
            },
        }
    }
    config_path = tmp_path / "models_config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")

    result = load_providers(config_path)

    assert result == {
        "openai": ("op://llmkeys/OpenAI/credential", "OPENAI_API_KEY"),
    }


def test_load_providers_skips_provider_without_op_reference(tmp_path):
    cfg = {
        "providers": {
            "openai": {
                "api_key_env": "OPENAI_API_KEY",
                "op_reference": "op://llmkeys/OpenAI/credential",
            },
            "legacy": {
                "api_key_env": "LEGACY_API_KEY"
            },
        }
    }
    config_path = tmp_path / "models_config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")

    result = load_providers(config_path)

    assert "openai" in result
    assert "legacy" not in result


def test_load_providers_filter_by_name(tmp_path):
    cfg = {
        "providers": {
            "openai": {
                "api_key_env": "OPENAI_API_KEY",
                "op_reference": "op://llmkeys/OpenAI/credential",
            },
            "anthropic": {
                "api_key_env": "ANTHROPIC_API_KEY",
                "op_reference": "op://llmkeys/Anthropic/credential",
            },
        }
    }
    config_path = tmp_path / "models_config.json"
    config_path.write_text(json.dumps(cfg), encoding="utf-8")

    result = load_providers(config_path, only="openai")

    assert list(result.keys()) == ["openai"]


def test_fetch_key_returns_stripped_stdout():
    with patch("key_sync.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, stdout="sk-12345\n", stderr=""
        )
        key = fetch_key("op://llmkeys/OpenAI/credential")
        assert key == "sk-12345"
        mock_run.assert_called_once_with(
            ["op", "read", "op://llmkeys/OpenAI/credential"],
            capture_output=True,
            text=True,
            check=False,
        )


def test_fetch_key_raises_oper_on_failure():
    with patch("key_sync.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error reading item"
        )
        with pytest.raises(OpError) as excinfo:
            fetch_key("op://llmkeys/Missing/credential")
        assert "error reading item" in str(excinfo.value)


def test_write_keys_env_creates_file_with_mode_600(tmp_path):
    target = tmp_path / "llm" / "keys.env"

    write_keys_env({"OPENAI_API_KEY": "sk-abc"}, target)

    assert target.exists()
    mode = target.stat().st_mode & 0o777
    assert mode == 0o600
    assert target.read_text(encoding="utf-8") == "OPENAI_API_KEY=sk-abc\n"


def test_write_keys_env_creates_parent_dir_with_mode_700(tmp_path):
    target = tmp_path / "llm" / "keys.env"

    write_keys_env({"OPENAI_API_KEY": "sk-abc"}, target)

    parent_mode = target.parent.stat().st_mode & 0o777
    assert parent_mode == 0o700


def test_write_keys_env_overwrites_existing(tmp_path):
    target = tmp_path / "keys.env"
    target.write_text("OLD=value\n", encoding="utf-8")

    write_keys_env({"NEW": "v"}, target)

    assert target.read_text(encoding="utf-8") == "NEW=v\n"


def test_write_keys_env_preserves_insertion_order(tmp_path):
    target = tmp_path / "keys.env"

    write_keys_env(
        {"A_KEY": "a", "B_KEY": "b", "C_KEY": "c"}, target
    )

    assert target.read_text(encoding="utf-8") == "A_KEY=a\nB_KEY=b\nC_KEY=c\n"
