"""Tests for key_sync module."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from key_sync import load_providers, fetch_key, OpError, write_keys_env, main


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


@pytest.fixture
def sample_config(tmp_path):
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
    return config_path


def test_main_happy_path_writes_all_keys(sample_config, tmp_path, monkeypatch, capsys):
    target = tmp_path / "keys.env"
    monkeypatch.setattr("key_sync.CONFIG_PATH", sample_config)
    monkeypatch.setattr("key_sync.KEYS_ENV_PATH", target)
    monkeypatch.setattr("key_sync.shutil.which", lambda _name: "/usr/local/bin/op")

    call_outputs = {
        "op://llmkeys/OpenAI/credential": "sk-openai\n",
        "op://llmkeys/Anthropic/credential": "sk-ant\n",
    }

    def fake_run(cmd, **_kwargs):
        ref = cmd[-1]
        return MagicMock(returncode=0, stdout=call_outputs[ref], stderr="")

    monkeypatch.setattr("key_sync.subprocess.run", fake_run)

    rc = main([])

    assert rc == 0
    contents = target.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-openai" in contents
    assert "ANTHROPIC_API_KEY=sk-ant" in contents
    out = capsys.readouterr().out
    assert "Wrote 2 keys" in out


def test_main_dry_run_does_not_call_op_or_write_file(
    sample_config, tmp_path, monkeypatch, capsys
):
    target = tmp_path / "keys.env"
    monkeypatch.setattr("key_sync.CONFIG_PATH", sample_config)
    monkeypatch.setattr("key_sync.KEYS_ENV_PATH", target)

    calls = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("key_sync.subprocess.run", fake_run)

    rc = main(["--dry-run"])

    assert rc == 0
    assert calls == []
    assert not target.exists()
    out = capsys.readouterr().out
    assert "op://llmkeys/OpenAI/credential" in out
    assert "OPENAI_API_KEY" in out


def test_main_missing_op_prints_install_hint(
    sample_config, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr("key_sync.CONFIG_PATH", sample_config)
    monkeypatch.setattr("key_sync.KEYS_ENV_PATH", tmp_path / "keys.env")
    monkeypatch.setattr("key_sync.shutil.which", lambda _name: None)

    rc = main([])

    assert rc == 1
    err = capsys.readouterr().err
    assert "brew install 1password-cli" in err


def test_main_unauthenticated_op_prints_cli_integration_hint(
    sample_config, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr("key_sync.CONFIG_PATH", sample_config)
    monkeypatch.setattr("key_sync.KEYS_ENV_PATH", tmp_path / "keys.env")
    monkeypatch.setattr("key_sync.shutil.which", lambda _name: "/usr/local/bin/op")

    def fake_run(_cmd, **_kwargs):
        return MagicMock(
            returncode=1, stdout="", stderr="Error: You are not signed in."
        )

    monkeypatch.setattr("key_sync.subprocess.run", fake_run)

    rc = main([])

    assert rc == 1
    err = capsys.readouterr().err
    assert "Integrate with 1Password CLI" in err


def test_main_partial_failure_writes_remaining_keys_and_exits_nonzero(
    sample_config, tmp_path, monkeypatch, capsys
):
    target = tmp_path / "keys.env"
    monkeypatch.setattr("key_sync.CONFIG_PATH", sample_config)
    monkeypatch.setattr("key_sync.KEYS_ENV_PATH", target)
    monkeypatch.setattr("key_sync.shutil.which", lambda _name: "/usr/local/bin/op")

    def fake_run(cmd, **_kwargs):
        ref = cmd[-1]
        if "OpenAI" in ref:
            return MagicMock(returncode=0, stdout="sk-openai\n", stderr="")
        return MagicMock(returncode=1, stdout="", stderr="item not found")

    monkeypatch.setattr("key_sync.subprocess.run", fake_run)

    rc = main([])

    assert rc == 1
    contents = target.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-openai" in contents
    assert "ANTHROPIC_API_KEY" not in contents
    err = capsys.readouterr().err
    assert "anthropic" in err.lower()


def test_main_single_provider_preserves_other_keys(
    sample_config, tmp_path, monkeypatch
):
    target = tmp_path / "keys.env"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "OPENAI_API_KEY=old-openai\nANTHROPIC_API_KEY=old-ant\n",
        encoding="utf-8",
    )
    os.chmod(target, 0o600)

    monkeypatch.setattr("key_sync.CONFIG_PATH", sample_config)
    monkeypatch.setattr("key_sync.KEYS_ENV_PATH", target)
    monkeypatch.setattr("key_sync.shutil.which", lambda _name: "/usr/local/bin/op")

    def fake_run(_cmd, **_kwargs):
        return MagicMock(returncode=0, stdout="sk-new-openai\n", stderr="")

    monkeypatch.setattr("key_sync.subprocess.run", fake_run)

    rc = main(["--provider", "openai"])

    assert rc == 0
    contents = target.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-new-openai" in contents
    assert "ANTHROPIC_API_KEY=old-ant" in contents


def test_main_full_sync_overwrites_untracked_keys(
    sample_config, tmp_path, monkeypatch
):
    target = tmp_path / "keys.env"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "OPENAI_API_KEY=old-openai\nCUSTOM_KEY=custom-value\n",
        encoding="utf-8",
    )
    os.chmod(target, 0o600)

    monkeypatch.setattr("key_sync.CONFIG_PATH", sample_config)
    monkeypatch.setattr("key_sync.KEYS_ENV_PATH", target)
    monkeypatch.setattr("key_sync.shutil.which", lambda _name: "/usr/local/bin/op")

    call_outputs = {
        "op://llmkeys/OpenAI/credential": "sk-new-openai\n",
        "op://llmkeys/Anthropic/credential": "sk-ant\n",
    }

    def fake_run(cmd, **_kwargs):
        ref = cmd[-1]
        return MagicMock(returncode=0, stdout=call_outputs[ref], stderr="")

    monkeypatch.setattr("key_sync.subprocess.run", fake_run)

    rc = main([])

    assert rc == 0
    contents = target.read_text(encoding="utf-8")
    # Full sync replaces file entirely with 1P contents (1P is SSoT)
    assert "OPENAI_API_KEY=sk-new-openai" in contents
    assert "ANTHROPIC_API_KEY=sk-ant" in contents
    assert "CUSTOM_KEY" not in contents
