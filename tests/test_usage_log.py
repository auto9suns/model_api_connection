"""Unit tests for usage_log."""

import datetime as dt
import json
import os
import socket
import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import usage_log


def test_usage_dir_default(monkeypatch):
    monkeypatch.delenv("LLM_USAGE_DIR", raising=False)
    expected = Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/llm-usage"
    assert usage_log._usage_dir() == expected


def test_usage_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path / "custom"))
    assert usage_log._usage_dir() == tmp_path / "custom"


def test_usage_file_uses_hostname(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    assert usage_log._usage_file() == tmp_path / f"{socket.gethostname()}.jsonl"


def test_write_record_creates_file(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))

    usage_log._write_record({"foo": "bar", "n": 1})

    expected = tmp_path / f"{socket.gethostname()}.jsonl"
    assert expected.exists()
    line = expected.read_text().strip()
    assert json.loads(line) == {"foo": "bar", "n": 1}


def test_write_record_appends(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))

    usage_log._write_record({"i": 1})
    usage_log._write_record({"i": 2})

    f = tmp_path / f"{socket.gethostname()}.jsonl"
    lines = [json.loads(l) for l in f.read_text().splitlines()]
    assert lines == [{"i": 1}, {"i": 2}]


def test_write_record_file_permissions(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))

    usage_log._write_record({"foo": "bar"})

    f = tmp_path / f"{socket.gethostname()}.jsonl"
    assert (f.stat().st_mode & 0o777) == 0o600


def test_write_record_dir_permissions(monkeypatch, tmp_path):
    target = tmp_path / "nested" / "llm-usage"
    monkeypatch.setenv("LLM_USAGE_DIR", str(target))

    usage_log._write_record({"foo": "bar"})

    assert target.exists()
    assert (target.stat().st_mode & 0o777) == 0o700


def test_write_record_unicode(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))

    usage_log._write_record({"msg": "你好"})

    f = tmp_path / f"{socket.gethostname()}.jsonl"
    assert "你好" in f.read_text()


def test_get_caller_uses_argv(monkeypatch):
    monkeypatch.delenv("LLM_CALLER", raising=False)
    monkeypatch.setattr(sys, "argv", ["/some/script.py"])
    caller = usage_log._get_caller()
    assert caller["caller_script"] == "/some/script.py"
    assert caller["caller_cwd"] == os.getcwd()
    assert isinstance(caller["caller_pid"], int)
    assert isinstance(caller["caller_ppid"], int)


def test_get_caller_env_var_wins(monkeypatch):
    monkeypatch.setenv("LLM_CALLER", "daily-summary")
    monkeypatch.setattr(sys, "argv", ["/some/script.py"])
    assert usage_log._get_caller()["caller_script"] == "daily-summary"


def test_get_caller_repl_fallback(monkeypatch):
    monkeypatch.delenv("LLM_CALLER", raising=False)
    monkeypatch.setattr(sys, "argv", [""])
    assert usage_log._get_caller()["caller_script"] == "<repl>"


def _fake_response(prompt_tokens=10, completion_tokens=5, content="hi"):
    r = MagicMock()
    r.usage.prompt_tokens = prompt_tokens
    r.usage.completion_tokens = completion_tokens
    r.choices = [MagicMock()]
    r.choices[0].message.content = content
    return r


def test_build_record_success_minimal(monkeypatch, tmp_path):
    monkeypatch.delenv("LLM_LOG_PAYLOAD", raising=False)
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))

    kwargs = {
        "model": "openai/gpt-4o",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
        "litellm_params": {"metadata": {"provider": "openai"}},
    }
    response = _fake_response(prompt_tokens=10, completion_tokens=5)
    start = dt.datetime(2026, 4, 20, 3, 0, 0, tzinfo=dt.timezone.utc)
    end = dt.datetime(2026, 4, 20, 3, 0, 1, 500000, tzinfo=dt.timezone.utc)

    with patch("usage_log.litellm.completion_cost", return_value=0.0312):
        rec = usage_log._build_record("success", kwargs, response, start, end)

    assert rec["status"] == "success"
    assert rec["provider"] == "openai"
    assert rec["model"] == "openai/gpt-4o"
    assert rec["input_tokens"] == 10
    assert rec["output_tokens"] == 5
    assert rec["cost_usd"] == 0.0312
    assert rec["latency_ms"] == 1500
    assert rec["stream"] is False
    assert rec["error"] is None
    assert "request_id" in rec
    assert "ts" in rec
    assert rec["ts"].endswith("Z")
    assert "prompt" not in rec
    assert "completion" not in rec


def test_build_record_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))

    kwargs = {
        "model": "openai/gpt-4o",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
        "litellm_params": {"metadata": {"provider": "openai"}},
    }
    err = ValueError("bad model")
    start = dt.datetime(2026, 4, 20, 3, 0, 0, tzinfo=dt.timezone.utc)
    end = dt.datetime(2026, 4, 20, 3, 0, 0, 100000, tzinfo=dt.timezone.utc)

    rec = usage_log._build_record("error", kwargs, err, start, end)

    assert rec["status"] == "error"
    assert "ValueError" in rec["error"]
    assert "bad model" in rec["error"]
    assert rec["input_tokens"] is None
    assert rec["output_tokens"] is None
    assert rec["cost_usd"] is None


def test_build_record_cost_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))

    kwargs = {
        "model": "openai/Pro/moonshotai/Kimi-K2.5",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
        "litellm_params": {"metadata": {"provider": "siliconflow"}},
    }
    response = _fake_response(prompt_tokens=100, completion_tokens=50)
    start = dt.datetime(2026, 4, 20, 3, 0, 0, tzinfo=dt.timezone.utc)
    end = dt.datetime(2026, 4, 20, 3, 0, 1, tzinfo=dt.timezone.utc)

    with patch("usage_log.litellm.completion_cost", side_effect=Exception("not in pricelist")):
        rec = usage_log._build_record("success", kwargs, response, start, end)

    assert rec["cost_usd"] is None
    assert rec["input_tokens"] == 100
    assert rec["output_tokens"] == 50


def test_build_record_payload_when_enabled(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_LOG_PAYLOAD", "1")
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))

    kwargs = {
        "model": "openai/gpt-4o",
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
        "litellm_params": {"metadata": {"provider": "openai"}},
    }
    response = _fake_response(content="pong")
    start = dt.datetime.now(dt.timezone.utc)
    end = start + dt.timedelta(milliseconds=200)

    with patch("usage_log.litellm.completion_cost", return_value=0.001):
        rec = usage_log._build_record("success", kwargs, response, start, end)

    assert rec["prompt"] == json.dumps([{"role": "user", "content": "ping"}], ensure_ascii=False)
    assert rec["completion"] == "pong"


def test_build_record_truncates_long_error(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))

    kwargs = {
        "model": "openai/gpt-4o",
        "messages": [],
        "stream": False,
        "litellm_params": {"metadata": {"provider": "openai"}},
    }
    err = RuntimeError("x" * 1000)
    start = dt.datetime.now(dt.timezone.utc)
    end = start

    rec = usage_log._build_record("error", kwargs, err, start, end)
    assert len(rec["error"]) <= 514  # "RuntimeError: " (14) + 500
