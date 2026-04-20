"""llm-stats CLI: aggregate LLM usage logs across machines."""

import datetime as dt
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterator


def _usage_dir() -> Path:
    raw = os.environ.get("LLM_USAGE_DIR")
    if raw:
        return Path(raw)
    return Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/llm-usage"


def _iter_records() -> Iterator[dict]:
    """Yield every JSONL record across all *.jsonl in USAGE_DIR. Skip corrupt lines."""
    d = _usage_dir()
    if not d.exists():
        return
    for f in sorted(d.glob("*.jsonl")):
        with open(f, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    print(f"[llm-stats] WARN: skipping {f.name}:{lineno}: {e}",
                          file=sys.stderr)


_REL_RE = re.compile(r"^(\d+)\s*(m|h|d)$")


def _parse_since(value: str, now: dt.datetime | None = None) -> dt.datetime:
    """Parse '1h' / '24h' / '7d' / '30m' or ISO 8601."""
    now = now or dt.datetime.now(dt.timezone.utc)
    m = _REL_RE.match(value.strip())
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        delta = {"m": dt.timedelta(minutes=n),
                 "h": dt.timedelta(hours=n),
                 "d": dt.timedelta(days=n)}[unit]
        return now - delta
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        parsed = dt.datetime.fromisoformat(s)
    except ValueError as e:
        raise ValueError(f"invalid --since: {value!r}") from e
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _parse_filter(specs: list[str]) -> list[tuple[str, str, str]]:
    """['provider=openai', 'caller~foo'] -> [(key, op, val), ...]."""
    out = []
    for spec in specs:
        if "~" in spec:
            k, v = spec.split("~", 1)
            out.append((k.strip(), "~", v.strip()))
        elif "=" in spec:
            k, v = spec.split("=", 1)
            out.append((k.strip(), "=", v.strip()))
        else:
            raise ValueError(f"invalid --filter: {spec!r} (use key=val or key~val)")
    return out


_FILTER_KEY_ALIASES = {
    "caller": "caller_script",
}


def _row_value(row: dict, key: str):
    return row.get(_FILTER_KEY_ALIASES.get(key, key))


def _apply_filters(rows, filters):
    for row in rows:
        ok = True
        for key, op, val in filters:
            actual = _row_value(row, key)
            if actual is None:
                ok = False
                break
            actual_str = str(actual)
            if op == "=" and actual_str != val:
                ok = False
                break
            if op == "~" and val not in actual_str:
                ok = False
                break
        if ok:
            yield row


def _apply_since(rows, cutoff: dt.datetime):
    for row in rows:
        ts = row.get("ts", "")
        s = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
        try:
            t = dt.datetime.fromisoformat(s)
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        if t >= cutoff:
            yield row


def _aggregate(rows, by: list[str]) -> list[dict]:
    """Group rows by `by` keys, summing tokens/cost and counting calls."""
    buckets = defaultdict(lambda: {
        "calls": 0, "input_tokens": 0, "output_tokens": 0,
        "cost_usd_sum": 0.0, "cost_usd_count": 0,
    })
    for row in rows:
        key = tuple(_row_value(row, k) for k in by)
        b = buckets[key]
        b["calls"] += 1
        b["input_tokens"] += row.get("input_tokens") or 0
        b["output_tokens"] += row.get("output_tokens") or 0
        if row.get("cost_usd") is not None:
            b["cost_usd_sum"] += float(row["cost_usd"])
            b["cost_usd_count"] += 1

    result = []
    for key, b in buckets.items():
        rec = {by[i]: key[i] for i in range(len(by))}
        rec["calls"] = b["calls"]
        rec["input_tokens"] = b["input_tokens"]
        rec["output_tokens"] = b["output_tokens"]
        rec["cost_usd"] = b["cost_usd_sum"] if b["cost_usd_count"] > 0 else None
        result.append(rec)
    return result
