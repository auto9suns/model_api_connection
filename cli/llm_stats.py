"""llm-stats CLI: aggregate LLM usage logs across machines."""

import json
import os
import sys
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
