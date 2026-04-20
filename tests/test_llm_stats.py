"""Unit tests for cli.llm_stats."""

import json
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _write_jsonl(p: Path, records: list[dict]) -> None:
    p.write_text("\n".join(json.dumps(r) for r in records) + "\n")


def _sample(ts="2026-04-20T03:00:00.000Z", host="hostA", provider="openai",
            model="openai/gpt-4o", caller="/scripts/foo.py", in_tok=10,
            out_tok=5, cost=0.001, status="success"):
    return {
        "ts": ts, "host": host, "provider": provider, "model": model,
        "caller_script": caller, "caller_cwd": "/", "caller_pid": 1, "caller_ppid": 1,
        "input_tokens": in_tok, "output_tokens": out_tok, "cost_usd": cost,
        "latency_ms": 100, "status": status, "error": None,
        "request_id": "abc", "stream": False,
    }


def test_load_jsonl_files_merges_hosts(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    _write_jsonl(tmp_path / "hostA.jsonl", [_sample(host="hostA"), _sample(host="hostA")])
    _write_jsonl(tmp_path / "hostB.jsonl", [_sample(host="hostB")])

    import importlib
    from cli import llm_stats
    importlib.reload(llm_stats)
    rows = list(llm_stats._iter_records())
    assert len(rows) == 3
    hosts = sorted(set(r["host"] for r in rows))
    assert hosts == ["hostA", "hostB"]


def test_load_jsonl_skips_corrupt_lines(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    f = tmp_path / "host.jsonl"
    f.write_text(json.dumps(_sample()) + "\n{not valid json\n" + json.dumps(_sample()) + "\n")

    import importlib
    from cli import llm_stats
    importlib.reload(llm_stats)
    rows = list(llm_stats._iter_records())
    assert len(rows) == 2
    assert "host.jsonl:2" in capsys.readouterr().err


def test_iter_records_empty_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    import importlib
    from cli import llm_stats
    importlib.reload(llm_stats)
    rows = list(llm_stats._iter_records())
    assert rows == []


def test_iter_records_dir_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path / "does-not-exist"))
    import importlib
    from cli import llm_stats
    importlib.reload(llm_stats)
    rows = list(llm_stats._iter_records())
    assert rows == []
