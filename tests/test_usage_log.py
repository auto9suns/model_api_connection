"""Unit tests for usage_log."""

import json
import os
import socket
import stat
import sys
from pathlib import Path
from unittest.mock import patch

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
