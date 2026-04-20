"""llm-stats CLI: aggregate LLM usage logs across machines."""

import argparse
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
        eq_pos = spec.find("=")
        tilde_pos = spec.find("~")
        if eq_pos == -1 and tilde_pos == -1:
            raise ValueError(f"invalid --filter: {spec!r} (use key=val or key~val)")
        if tilde_pos != -1 and (eq_pos == -1 or tilde_pos < eq_pos):
            k, v = spec.split("~", 1)
            out.append((k.strip(), "~", v.strip()))
        else:
            k, v = spec.split("=", 1)
            out.append((k.strip(), "=", v.strip()))
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


def _format_value(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def _format_table(rows: list[dict], columns: list[str]) -> str:
    if not rows:
        return "(no data)"
    header = list(columns)
    data = [[_format_value(r.get(c)) for c in columns] for r in rows]
    widths = [max(len(header[i]), *(len(row[i]) for row in data)) for i in range(len(columns))]
    sep = "  "
    lines = [sep.join(header[i].ljust(widths[i]) for i in range(len(columns)))]
    lines.append(sep.join("-" * widths[i] for i in range(len(columns))))
    for row in data:
        lines.append(sep.join(row[i].ljust(widths[i]) for i in range(len(columns))))
    return "\n".join(lines)


def _print_summary(records: list[dict]) -> None:
    total = len(records)
    total_cost = sum(r.get("cost_usd") or 0 for r in records)
    failures = sum(1 for r in records if r.get("status") == "error")
    rate = (failures / total * 100) if total else 0.0
    print(f"调用:   {total:,} 次")
    print(f"成本:   ${total_cost:.4f}")
    print(f"失败率: {rate:.1f}% ({failures} 次)")


def _print_paths() -> None:
    d = _usage_dir()
    print(f"USAGE_DIR: {d}")
    if not d.exists():
        print("(目录不存在；跑一次 chat() 后会自动创建)")
        return
    files = sorted(d.glob("*.jsonl"))
    if not files:
        print("(目录为空)")
        return
    for f in files:
        with open(f, "r", encoding="utf-8") as fh:
            n_lines = sum(1 for _ in fh)
        size_kb = f.stat().st_size / 1024
        print(f"  {f.name:30s}  {n_lines:>6d} 行  {size_kb:>8.1f} KB")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="llm-stats", description="查询本机 + 多端 LLM 调用日志")
    p.add_argument("--since", default="24h", help="时间窗口：1h / 24h / 7d / 30m / ISO")
    p.add_argument("--by", default="provider",
                   help="group by 键（可逗号分隔）：provider / model / caller / host")
    p.add_argument("--filter", action="append", default=[],
                   help="key=val 精确匹配 / key~val 子串；可多次")
    p.add_argument("--raw", action="store_true", help="原始 JSONL 输出，便于 jq")
    p.add_argument("--tail", type=int, default=0, help="只看最近 N 条原始记录")
    p.add_argument("--paths", action="store_true", help="打印 USAGE_DIR 和各文件状态")
    args = p.parse_args(argv)

    if args.paths:
        _print_paths()
        return 0

    records = list(_iter_records())

    # Apply --since and --filter first (applies to ALL modes including --tail)
    try:
        cutoff = _parse_since(args.since)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    records = list(_apply_since(records, cutoff))

    try:
        filters = _parse_filter(args.filter)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    records = list(_apply_filters(records, filters))

    if args.tail > 0:
        records = sorted(records, key=lambda r: r.get("ts", ""))[-args.tail:]
        if args.raw:
            for r in records:
                print(json.dumps(r, ensure_ascii=False))
        else:
            cols = ["ts", "host", "provider", "model", "caller_script",
                    "input_tokens", "output_tokens", "cost_usd", "status"]
            print(_format_table(records, cols))
        return 0

    if not records:
        print(f"(no data in window since={args.since}, filter={args.filter})")
        return 0

    if args.raw:
        for r in records:
            print(json.dumps(r, ensure_ascii=False))
        return 0

    print(f"窗口: {args.since}")
    _print_summary(records)
    print()

    by_keys = [k.strip() for k in args.by.split(",") if k.strip()]
    aggregated = _aggregate(records, by=by_keys)
    aggregated.sort(key=lambda r: r.get("calls", 0), reverse=True)
    cols = by_keys + ["calls", "input_tokens", "output_tokens", "cost_usd"]
    print(f"按 {', '.join(by_keys)}:")
    print(_format_table(aggregated, cols))
    return 0


if __name__ == "__main__":
    sys.exit(main())
