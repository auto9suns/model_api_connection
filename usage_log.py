"""LLM 调用日志：通过 litellm callback 自动记录每次 chat() 到 JSONL。"""

import json
import os
import socket
import sys
from pathlib import Path


def _usage_dir() -> Path:
    raw = os.environ.get("LLM_USAGE_DIR")
    if raw:
        return Path(raw)
    return Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/llm-usage"


def _usage_file() -> Path:
    return _usage_dir() / f"{socket.gethostname()}.jsonl"


def _write_record(record: dict) -> None:
    """Append a record as a single JSON line. Atomic on POSIX for lines < PIPE_BUF."""
    target = _usage_file()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    existed = target.exists()
    with open(target, "a", encoding="utf-8") as f:
        f.write(line)
    if not existed:
        target.chmod(0o600)


def _get_caller() -> dict:
    return {
        "caller_script": os.environ.get("LLM_CALLER") or sys.argv[0] or "<repl>",
        "caller_cwd": os.getcwd(),
        "caller_pid": os.getpid(),
        "caller_ppid": os.getppid(),
    }
