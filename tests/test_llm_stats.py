"""Unit tests for cli.llm_stats."""

import datetime as dt
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


def test_parse_since_relative():
    from cli import llm_stats
    now = dt.datetime(2026, 4, 20, 12, 0, 0, tzinfo=dt.timezone.utc)
    assert llm_stats._parse_since("1h", now=now) == now - dt.timedelta(hours=1)
    assert llm_stats._parse_since("24h", now=now) == now - dt.timedelta(hours=24)
    assert llm_stats._parse_since("7d", now=now) == now - dt.timedelta(days=7)
    assert llm_stats._parse_since("30m", now=now) == now - dt.timedelta(minutes=30)


def test_parse_since_iso():
    from cli import llm_stats
    parsed = llm_stats._parse_since("2026-04-19T00:00:00Z")
    assert parsed.year == 2026 and parsed.month == 4 and parsed.day == 19


def test_parse_since_invalid():
    from cli import llm_stats
    with pytest.raises(ValueError):
        llm_stats._parse_since("nonsense")


def test_parse_filter_simple():
    from cli import llm_stats
    f = llm_stats._parse_filter(["provider=openai"])
    assert f == [("provider", "=", "openai")]


def test_parse_filter_substring():
    from cli import llm_stats
    f = llm_stats._parse_filter(["caller~bar.py"])
    assert f == [("caller", "~", "bar.py")]


def test_parse_filter_multiple():
    from cli import llm_stats
    f = llm_stats._parse_filter(["provider=openai", "host=mac1"])
    assert ("provider", "=", "openai") in f and ("host", "=", "mac1") in f


def test_apply_filter_exact():
    from cli import llm_stats
    rows = [_sample(provider="openai"), _sample(provider="anthropic")]
    out = list(llm_stats._apply_filters(rows, [("provider", "=", "openai")]))
    assert len(out) == 1 and out[0]["provider"] == "openai"


def test_apply_filter_substring_caller():
    from cli import llm_stats
    rows = [
        _sample(caller="/work/runaway.py"),
        _sample(caller="/work/safe.py"),
    ]
    out = list(llm_stats._apply_filters(rows, [("caller", "~", "runaway")]))
    assert len(out) == 1 and "runaway" in out[0]["caller_script"]


def test_apply_filter_combined_and():
    from cli import llm_stats
    rows = [
        _sample(provider="openai", host="mac1"),
        _sample(provider="openai", host="mac2"),
        _sample(provider="anthropic", host="mac1"),
    ]
    out = list(llm_stats._apply_filters(rows,
        [("provider", "=", "openai"), ("host", "=", "mac1")]))
    assert len(out) == 1


def test_apply_since():
    from cli import llm_stats
    cutoff = dt.datetime(2026, 4, 20, 0, 0, 0, tzinfo=dt.timezone.utc)
    rows = [
        _sample(ts="2026-04-19T23:00:00.000Z"),
        _sample(ts="2026-04-20T01:00:00.000Z"),
    ]
    out = list(llm_stats._apply_since(rows, cutoff))
    assert len(out) == 1
    assert out[0]["ts"].startswith("2026-04-20")


def test_aggregate_by_provider():
    from cli import llm_stats
    rows = [
        _sample(provider="openai", in_tok=10, out_tok=5, cost=0.01),
        _sample(provider="openai", in_tok=20, out_tok=10, cost=0.02),
        _sample(provider="anthropic", in_tok=5, out_tok=2, cost=0.005),
    ]
    result = llm_stats._aggregate(rows, by=["provider"])
    by_provider = {r["provider"]: r for r in result}
    assert by_provider["openai"]["calls"] == 2
    assert by_provider["openai"]["input_tokens"] == 30
    assert by_provider["openai"]["output_tokens"] == 15
    assert by_provider["openai"]["cost_usd"] == pytest.approx(0.03)
    assert by_provider["anthropic"]["calls"] == 1


def test_aggregate_handles_null_cost():
    from cli import llm_stats
    rows = [
        _sample(provider="siliconflow", cost=None),
        _sample(provider="siliconflow", cost=None),
    ]
    result = llm_stats._aggregate(rows, by=["provider"])
    assert result[0]["cost_usd"] is None  # all null → aggregate is null


def test_aggregate_mixed_null_cost():
    from cli import llm_stats
    rows = [
        _sample(provider="x", cost=0.01),
        _sample(provider="x", cost=None),
    ]
    result = llm_stats._aggregate(rows, by=["provider"])
    assert result[0]["cost_usd"] == pytest.approx(0.01)


def test_aggregate_by_combined_keys():
    from cli import llm_stats
    rows = [
        _sample(provider="openai", host="mac1"),
        _sample(provider="openai", host="mac2"),
        _sample(provider="openai", host="mac1"),
    ]
    result = llm_stats._aggregate(rows, by=["provider", "host"])
    keys = sorted((r["provider"], r["host"]) for r in result)
    assert keys == [("openai", "mac1"), ("openai", "mac2")]
    by_key = {(r["provider"], r["host"]): r for r in result}
    assert by_key[("openai", "mac1")]["calls"] == 2
