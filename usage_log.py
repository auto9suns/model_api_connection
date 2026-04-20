"""LLM 调用日志：通过 litellm callback 自动记录每次 chat() 到 JSONL。"""

import datetime as dt
import json
import os
import socket
import sys
import uuid
from pathlib import Path

import litellm


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


_ERROR_MAX_LEN = 500


def _build_record(status: str, kwargs: dict, response, start_time: dt.datetime, end_time: dt.datetime) -> dict:
    """Build one log record from a litellm callback's arguments."""
    metadata = (kwargs.get("litellm_params") or {}).get("metadata") or {}
    provider = metadata.get("provider", "<unknown>")

    input_tokens = output_tokens = cost_usd = None
    error = None
    completion_text = None

    if status == "success":
        try:
            input_tokens = int(response.usage.prompt_tokens)
            output_tokens = int(response.usage.completion_tokens)
        except Exception:
            input_tokens = output_tokens = None
        try:
            cost_usd = float(litellm.completion_cost(response))
        except Exception:
            cost_usd = None
        try:
            completion_text = response.choices[0].message.content
        except Exception:
            completion_text = None
    else:
        prefix = f"{type(response).__name__}: "
        msg = prefix + str(response)
        error = msg[: len(prefix) + _ERROR_MAX_LEN]

    ts = end_time.astimezone(dt.timezone.utc)
    ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"

    record = {
        "ts": ts_str,
        "host": socket.gethostname(),
        "provider": provider,
        "model": kwargs.get("model", ""),
        **_get_caller(),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "latency_ms": int((end_time - start_time).total_seconds() * 1000),
        "status": status,
        "error": error,
        "request_id": uuid.uuid4().hex,
        "stream": bool(kwargs.get("stream", False)),
    }

    if os.environ.get("LLM_LOG_PAYLOAD") == "1":
        try:
            record["prompt"] = json.dumps(kwargs.get("messages") or [], ensure_ascii=False)
        except Exception:
            record["prompt"] = None
        record["completion"] = completion_text

    return record


def _stderr_warn(msg: str) -> None:
    print(f"[usage_log] WARN: {msg}", file=sys.stderr)


def _log_success(kwargs, response, start_time, end_time):
    try:
        _write_record(_build_record("success", kwargs, response, start_time, end_time))
    except Exception as e:
        _stderr_warn(f"success callback failed: {type(e).__name__}: {e}")


def _log_failure(kwargs, response, start_time, end_time):
    try:
        _write_record(_build_record("error", kwargs, response, start_time, end_time))
    except Exception as e:
        _stderr_warn(f"failure callback failed: {type(e).__name__}: {e}")


def register() -> None:
    """Register usage_log callbacks with litellm. Idempotent."""
    if _log_success not in litellm.success_callback:
        litellm.success_callback.append(_log_success)
    if _log_failure not in litellm.failure_callback:
        litellm.failure_callback.append(_log_failure)
