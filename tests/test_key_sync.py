"""Tests for key_sync module."""

import json
from pathlib import Path

import pytest

from key_sync import load_providers


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
