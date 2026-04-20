# LLM Usage Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `model_api_connection` 加全自动 LLM 调用日志（每机一份 JSONL，iCloud 同步多端聚合），并提供 `llm-stats` CLI 查询。Consumer 项目零侵入。

**Architecture:** `usage_log.py` 通过 litellm 内置 `success_callback` / `failure_callback` 在每次 `chat()` 完成后追加一行 JSON 到 `~/<iCloud>/llm-usage/<hostname>.jsonl`。`cli/llm_stats.py` 把所有 `*.jsonl` 加载到内存 SQLite，按 `--since` / `--by` / `--filter` 聚合输出。

**Tech Stack:** Python 3.10+, litellm, pytest, sqlite3 (stdlib), argparse (stdlib)。无新增第三方依赖。

**Spec:** `docs/superpowers/specs/2026-04-20-llm-usage-logging-design.md`

---

## File Structure

| 文件 | 责任 | 是否新建 |
|------|------|----------|
| `usage_log.py` | 路径管理、JSONL 追加、record 构建、caller 识别、callback 注册 | 新建 |
| `cli/__init__.py` | 空文件，标识子包 | 新建 |
| `cli/llm_stats.py` | `llm-stats` CLI：加载 JSONL、聚合、过滤、输出 | 新建 |
| `tests/test_usage_log.py` | usage_log 单测 | 新建 |
| `tests/test_llm_stats.py` | CLI 单测 | 新建 |
| `model_connector.py` | 顶部追加 `from usage_log import register; register()` | 修改 |
| `pyproject.toml` | 加 `[project.scripts] llm-stats = "cli.llm_stats:main"` + `packages = ["cli"]` + `py-modules` 加 `usage_log` | 修改 |
| `README.md` | 新增"LLM 用量监控"章节 | 修改 |

---

## Task 1: `usage_log.py` — 路径与 JSONL 写入

**Files:**
- Create: `usage_log.py`
- Test: `tests/test_usage_log.py`

- [ ] **Step 1.1: 写失败测试 — 路径解析**

新建 `tests/test_usage_log.py`：

```python
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


def test_usage_dir_default(monkeypatch):
    monkeypatch.delenv("LLM_USAGE_DIR", raising=False)
    import importlib
    import usage_log
    importlib.reload(usage_log)
    expected = Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/llm-usage"
    assert usage_log._usage_dir() == expected


def test_usage_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path / "custom"))
    import importlib
    import usage_log
    importlib.reload(usage_log)
    assert usage_log._usage_dir() == tmp_path / "custom"


def test_usage_file_uses_hostname(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    import importlib
    import usage_log
    importlib.reload(usage_log)
    assert usage_log._usage_file() == tmp_path / f"{socket.gethostname()}.jsonl"
```

- [ ] **Step 1.2: 跑测试确认失败**

Run: `cd $WORKSPACE_ROOT/model_api_connection && pytest tests/test_usage_log.py -v`
Expected: `ModuleNotFoundError: No module named 'usage_log'`

- [ ] **Step 1.3: 创建最小 `usage_log.py`**

```python
"""LLM 调用日志：通过 litellm callback 自动记录每次 chat() 到 JSONL。

详见 docs/superpowers/specs/2026-04-20-llm-usage-logging-design.md
"""

import os
import socket
from pathlib import Path


def _usage_dir() -> Path:
    raw = os.environ.get("LLM_USAGE_DIR")
    if raw:
        return Path(raw)
    return Path.home() / "Library/Mobile Documents/iCloud~md~obsidian/Documents/llm-usage"


def _usage_file() -> Path:
    return _usage_dir() / f"{socket.gethostname()}.jsonl"
```

- [ ] **Step 1.4: 跑测试确认通过**

Run: `pytest tests/test_usage_log.py -v`
Expected: 3 passed

- [ ] **Step 1.5: 写 writer 失败测试**

追加到 `tests/test_usage_log.py`：

```python
def test_write_record_creates_file(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    import importlib
    import usage_log
    importlib.reload(usage_log)

    usage_log._write_record({"foo": "bar", "n": 1})

    expected = tmp_path / f"{socket.gethostname()}.jsonl"
    assert expected.exists()
    line = expected.read_text().strip()
    assert json.loads(line) == {"foo": "bar", "n": 1}


def test_write_record_appends(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    import importlib
    import usage_log
    importlib.reload(usage_log)

    usage_log._write_record({"i": 1})
    usage_log._write_record({"i": 2})

    f = tmp_path / f"{socket.gethostname()}.jsonl"
    lines = [json.loads(l) for l in f.read_text().splitlines()]
    assert lines == [{"i": 1}, {"i": 2}]


def test_write_record_file_permissions(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    import importlib
    import usage_log
    importlib.reload(usage_log)

    usage_log._write_record({"foo": "bar"})

    f = tmp_path / f"{socket.gethostname()}.jsonl"
    assert (f.stat().st_mode & 0o777) == 0o600


def test_write_record_dir_permissions(monkeypatch, tmp_path):
    target = tmp_path / "nested" / "llm-usage"
    monkeypatch.setenv("LLM_USAGE_DIR", str(target))
    import importlib
    import usage_log
    importlib.reload(usage_log)

    usage_log._write_record({"foo": "bar"})

    assert target.exists()
    assert (target.stat().st_mode & 0o777) == 0o700


def test_write_record_unicode(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    import importlib
    import usage_log
    importlib.reload(usage_log)

    usage_log._write_record({"msg": "你好"})

    f = tmp_path / f"{socket.gethostname()}.jsonl"
    assert "你好" in f.read_text()
```

- [ ] **Step 1.6: 跑测试确认失败**

Run: `pytest tests/test_usage_log.py -v`
Expected: 5 new tests fail with `AttributeError: module 'usage_log' has no attribute '_write_record'`

- [ ] **Step 1.7: 实现 `_write_record`**

追加到 `usage_log.py`：

```python
import json


def _write_record(record: dict) -> None:
    """Append a record as a single JSON line. Atomic on POSIX for lines < PIPE_BUF."""
    target = _usage_file()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with open(target, "a", encoding="utf-8") as f:
        f.write(line)
    if (target.stat().st_mode & 0o777) != 0o600:
        target.chmod(0o600)
```

- [ ] **Step 1.8: 跑测试确认全部通过**

Run: `pytest tests/test_usage_log.py -v`
Expected: 8 passed

- [ ] **Step 1.9: Commit**

```bash
git add usage_log.py tests/test_usage_log.py
git commit -m "$(cat <<'EOF'
feat(usage-log): 路径解析与 JSONL writer

Why: 多端多项目调用 LLM 缺统一日志，先实现底层 writer。
What:
- usage_log.py: _usage_dir / _usage_file（支持 LLM_USAGE_DIR 覆盖）
- usage_log.py: _write_record append-only JSONL，文件 0600 / 目录 0700
- tests/test_usage_log.py: 8 个单测覆盖路径、追加、权限、Unicode
EOF
)"
```

---

## Task 2: `usage_log.py` — caller 识别

**Files:**
- Modify: `usage_log.py`
- Test: `tests/test_usage_log.py`

- [ ] **Step 2.1: 写失败测试**

追加到 `tests/test_usage_log.py`：

```python
def test_get_caller_uses_argv(monkeypatch):
    monkeypatch.delenv("LLM_CALLER", raising=False)
    monkeypatch.setattr(sys, "argv", ["/some/script.py"])
    import importlib
    import usage_log
    importlib.reload(usage_log)

    caller = usage_log._get_caller()
    assert caller["caller_script"] == "/some/script.py"
    assert caller["caller_cwd"] == os.getcwd()
    assert isinstance(caller["caller_pid"], int)
    assert isinstance(caller["caller_ppid"], int)


def test_get_caller_env_var_wins(monkeypatch):
    monkeypatch.setenv("LLM_CALLER", "daily-summary")
    monkeypatch.setattr(sys, "argv", ["/some/script.py"])
    import importlib
    import usage_log
    importlib.reload(usage_log)

    assert usage_log._get_caller()["caller_script"] == "daily-summary"


def test_get_caller_repl_fallback(monkeypatch):
    monkeypatch.delenv("LLM_CALLER", raising=False)
    monkeypatch.setattr(sys, "argv", [""])
    import importlib
    import usage_log
    importlib.reload(usage_log)

    assert usage_log._get_caller()["caller_script"] == "<repl>"
```

- [ ] **Step 2.2: 跑测试确认失败**

Run: `pytest tests/test_usage_log.py::test_get_caller_uses_argv -v`
Expected: `AttributeError: module 'usage_log' has no attribute '_get_caller'`

- [ ] **Step 2.3: 实现 `_get_caller`**

追加到 `usage_log.py`：

```python
import sys


def _get_caller() -> dict:
    return {
        "caller_script": os.environ.get("LLM_CALLER") or sys.argv[0] or "<repl>",
        "caller_cwd": os.getcwd(),
        "caller_pid": os.getpid(),
        "caller_ppid": os.getppid(),
    }
```

- [ ] **Step 2.4: 跑测试确认通过**

Run: `pytest tests/test_usage_log.py -v`
Expected: 11 passed

- [ ] **Step 2.5: Commit**

```bash
git add usage_log.py tests/test_usage_log.py
git commit -m "$(cat <<'EOF'
feat(usage-log): caller 识别（LLM_CALLER 环境变量优先）

Why: cron / launchd 任务需要显式署名，便于事后追溯调用方。
What:
- _get_caller 返回 caller_script / cwd / pid / ppid
- 优先级：LLM_CALLER > sys.argv[0] > "<repl>"
- 3 个单测覆盖 env / argv / repl 三种场景
EOF
)"
```

---

## Task 3: `usage_log.py` — record builder

**Files:**
- Modify: `usage_log.py`
- Test: `tests/test_usage_log.py`

- [ ] **Step 3.1: 写失败测试 — 成功 record**

追加到 `tests/test_usage_log.py`：

```python
from unittest.mock import MagicMock
import datetime as dt


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
    import importlib
    import usage_log
    importlib.reload(usage_log)

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
    import importlib
    import usage_log
    importlib.reload(usage_log)

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
    import importlib
    import usage_log
    importlib.reload(usage_log)

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
    import importlib
    import usage_log
    importlib.reload(usage_log)

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
    import importlib
    import usage_log
    importlib.reload(usage_log)

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
    assert len(rec["error"]) <= 500 + len("RuntimeError: ")
```

- [ ] **Step 3.2: 跑测试确认失败**

Run: `pytest tests/test_usage_log.py -v -k build_record`
Expected: 5 tests fail with `AttributeError: module 'usage_log' has no attribute '_build_record'`

- [ ] **Step 3.3: 实现 `_build_record`**

追加到 `usage_log.py`（顶部 import 段加上 `import datetime as dt`、`import uuid`、`import litellm`）：

```python
import datetime as dt
import uuid

import litellm


_ERROR_MAX_LEN = 500


def _build_record(status, kwargs, response, start_time, end_time) -> dict:
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
            pass
        try:
            cost_usd = float(litellm.completion_cost(response))
        except Exception:
            cost_usd = None
        try:
            completion_text = response.choices[0].message.content
        except Exception:
            completion_text = None
    else:
        msg = f"{type(response).__name__}: {response}"
        error = msg[: _ERROR_MAX_LEN + len(type(response).__name__) + 2]

    record = {
        "ts": _iso_now(),
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


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.datetime.now(dt.timezone.utc).microsecond // 1000:03d}Z"
```

- [ ] **Step 3.4: 跑测试确认通过**

Run: `pytest tests/test_usage_log.py -v`
Expected: 16 passed

- [ ] **Step 3.5: Commit**

```bash
git add usage_log.py tests/test_usage_log.py
git commit -m "$(cat <<'EOF'
feat(usage-log): record builder（success / error / payload 开关）

Why: callback 触发后需要把零散参数拼成一行结构化日志。
What:
- _build_record 处理 success / error 两路
- cost 算不出（如 SiliconFlow / Poe）fallback 为 null
- LLM_LOG_PAYLOAD=1 时附带 prompt / completion
- error 字段截断到 500 字符
- 5 个单测覆盖正常 / 失败 / 缺 cost / payload 开关 / 截断
EOF
)"
```

---

## Task 4: `usage_log.py` — callback 注册与异常隔离

**Files:**
- Modify: `usage_log.py`
- Test: `tests/test_usage_log.py`

- [ ] **Step 4.1: 写失败测试**

追加到 `tests/test_usage_log.py`：

```python
def test_register_idempotent(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    import importlib
    import litellm as _litellm
    import usage_log
    importlib.reload(usage_log)

    _litellm.success_callback = []
    _litellm.failure_callback = []

    usage_log.register()
    usage_log.register()
    usage_log.register()

    assert _litellm.success_callback.count(usage_log._log_success) == 1
    assert _litellm.failure_callback.count(usage_log._log_failure) == 1


def test_log_success_writes_record(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    import importlib
    import usage_log
    importlib.reload(usage_log)

    kwargs = {
        "model": "openai/gpt-4o",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": False,
        "litellm_params": {"metadata": {"provider": "openai"}},
    }
    response = _fake_response()
    start = dt.datetime.now(dt.timezone.utc)
    end = start + dt.timedelta(milliseconds=100)

    with patch("usage_log.litellm.completion_cost", return_value=0.001):
        usage_log._log_success(kwargs, response, start, end)

    f = tmp_path / f"{socket.gethostname()}.jsonl"
    assert f.exists()
    rec = json.loads(f.read_text().strip())
    assert rec["status"] == "success"
    assert rec["provider"] == "openai"


def test_log_failure_writes_record(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    import importlib
    import usage_log
    importlib.reload(usage_log)

    kwargs = {
        "model": "openai/gpt-4o",
        "messages": [],
        "stream": False,
        "litellm_params": {"metadata": {"provider": "openai"}},
    }
    err = RuntimeError("boom")
    start = dt.datetime.now(dt.timezone.utc)
    end = start

    usage_log._log_failure(kwargs, err, start, end)

    f = tmp_path / f"{socket.gethostname()}.jsonl"
    rec = json.loads(f.read_text().strip())
    assert rec["status"] == "error"
    assert "boom" in rec["error"]


def test_callback_swallows_exception(monkeypatch, tmp_path, capsys):
    """If the writer fails, callback should warn on stderr but not raise."""
    monkeypatch.setenv("LLM_USAGE_DIR", "/dev/null/cannot-write")
    import importlib
    import usage_log
    importlib.reload(usage_log)

    kwargs = {
        "model": "openai/gpt-4o",
        "messages": [],
        "stream": False,
        "litellm_params": {"metadata": {"provider": "openai"}},
    }
    response = _fake_response()
    start = dt.datetime.now(dt.timezone.utc)
    end = start

    # Should not raise
    usage_log._log_success(kwargs, response, start, end)

    captured = capsys.readouterr()
    assert "usage_log" in captured.err.lower()
```

- [ ] **Step 4.2: 跑测试确认失败**

Run: `pytest tests/test_usage_log.py -v -k 'register or log_success or log_failure or swallows'`
Expected: 4 fail with AttributeError on `register` / `_log_success` / `_log_failure`

- [ ] **Step 4.3: 实现 `register` 和 callback**

追加到 `usage_log.py`：

```python
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
```

- [ ] **Step 4.4: 跑测试确认通过**

Run: `pytest tests/test_usage_log.py -v`
Expected: 20 passed

- [ ] **Step 4.5: Commit**

```bash
git add usage_log.py tests/test_usage_log.py
git commit -m "$(cat <<'EOF'
feat(usage-log): callback 注册 + 异常隔离

Why: 日志逻辑挂掉不能让消费方的 chat() 跟着抛异常。
What:
- register() 幂等注册到 litellm.success/failure_callback
- _log_success / _log_failure 包 try/except，挂了走 stderr 警告
- 4 个单测：幂等性、success、failure、写失败时不抛
EOF
)"
```

---

## Task 5: `model_connector.py` 集成

**Files:**
- Modify: `model_connector.py`
- Test: `tests/test_usage_log_integration.py` (新建)

- [ ] **Step 5.1: 写集成测试**

新建 `tests/test_usage_log_integration.py`：

```python
"""Integration test: importing model_connector triggers usage_log.register()."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_import_model_connector_registers_callbacks(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    import importlib
    import litellm
    litellm.success_callback = []
    litellm.failure_callback = []

    import usage_log
    importlib.reload(usage_log)
    import model_connector
    importlib.reload(model_connector)

    assert usage_log._log_success in litellm.success_callback
    assert usage_log._log_failure in litellm.failure_callback


def test_chat_provider_passes_through_to_metadata(monkeypatch, tmp_path):
    """chat() must put the provider key into litellm metadata so the callback can record it."""
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    import importlib
    import usage_log
    importlib.reload(usage_log)

    import model_connector
    importlib.reload(model_connector)

    from unittest.mock import MagicMock, patch

    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "ok"

    config = {"providers": {"openai": {
        "api_key_env": "OPENAI_API_KEY",
        "default_model": "gpt-4o",
        "models": {"gpt-4o": "openai/gpt-4o"},
    }}}
    import json as _json
    cfg = tmp_path / "models_config.json"
    cfg.write_text(_json.dumps(config))

    llm = model_connector.LLMConnector(config_path=cfg, api_keys={"openai": "sk-test"})

    with patch("model_connector.litellm.completion", return_value=mock_response) as mock_comp:
        llm.chat("hi", provider="openai")
        call_kwargs = mock_comp.call_args[1]
        meta = (call_kwargs.get("metadata") or {})
        assert meta.get("provider") == "openai"
```

- [ ] **Step 5.2: 跑测试确认失败**

Run: `pytest tests/test_usage_log_integration.py -v`
Expected: 1 test fails: `_log_success not in litellm.success_callback`. 2nd test fails: `meta.get("provider") is None`.

- [ ] **Step 5.3: 修改 `model_connector.py` — 注册 callback**

在 `model_connector.py` 的 `import litellm` 之后、`__all__` 之前追加：

```python
from usage_log import register as _register_usage_log

_register_usage_log()
```

- [ ] **Step 5.4: 修改 `model_connector.py` — 把 provider 传给 litellm metadata**

修改 `LLMConnector.chat()` 内 `litellm_kwargs` 的构建（约 model_connector.py:113-119），把 provider 加进 metadata：

```python
litellm_kwargs = {
    "model": model_id,
    "messages": messages,
    "stream": stream,
    "api_key": api_key,
    "metadata": {**kwargs.pop("metadata", {}), "provider": provider},
    **kwargs,
}
```

- [ ] **Step 5.5: 跑全部测试**

Run: `pytest tests/ -v`
Expected: All tests pass (existing + new). The previously-passing `test_chat_*` tests should still pass since `metadata` is just an additional kwarg.

- [ ] **Step 5.6: Commit**

```bash
git add model_connector.py tests/test_usage_log_integration.py
git commit -m "$(cat <<'EOF'
feat(connector): 自动注册 usage_log callback + 透传 provider 到 metadata

Why: 让任何 import model_connector 的项目自动开启日志，零侵入；
callback 需要从 metadata 拿到 provider 名（litellm 默认只有 model_id）。
What:
- model_connector.py: import 时调用 usage_log.register()
- chat() 把 provider 放进 litellm metadata，供 callback 提取
- 2 个集成测试：注册成功 + provider metadata 透传
EOF
)"
```

---

## Task 6: `cli/llm_stats.py` — 加载与解析 JSONL

**Files:**
- Create: `cli/__init__.py`
- Create: `cli/llm_stats.py`
- Test: `tests/test_llm_stats.py`

- [ ] **Step 6.1: 创建空 `cli/__init__.py`**

```bash
mkdir -p cli
touch cli/__init__.py
```

- [ ] **Step 6.2: 写失败测试**

新建 `tests/test_llm_stats.py`：

```python
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
```

- [ ] **Step 6.3: 跑测试确认失败**

Run: `pytest tests/test_llm_stats.py -v`
Expected: `ModuleNotFoundError: No module named 'cli'` or `AttributeError`

- [ ] **Step 6.4: 实现 `_iter_records`**

新建 `cli/llm_stats.py`：

```python
"""llm-stats CLI: aggregate LLM usage logs across machines.

详见 docs/superpowers/specs/2026-04-20-llm-usage-logging-design.md
"""

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
```

- [ ] **Step 6.5: 跑测试确认通过**

Run: `pytest tests/test_llm_stats.py -v`
Expected: 4 passed

- [ ] **Step 6.6: Commit**

```bash
git add cli/__init__.py cli/llm_stats.py tests/test_llm_stats.py
git commit -m "$(cat <<'EOF'
feat(cli): llm-stats — JSONL 加载与多端合并

Why: 多机日志靠 iCloud 同步到 USAGE_DIR/*.jsonl，CLI 需要一次性合并读取。
What:
- cli/llm_stats.py: _usage_dir / _iter_records 跨文件迭代
- 损坏行 skip + stderr 警告（保留行号）
- 目录缺失/为空时返回空，不抛
- 4 个单测：合并、损坏行、空目录、缺失目录
EOF
)"
```

---

## Task 7: `cli/llm_stats.py` — since / by / filter 查询

**Files:**
- Modify: `cli/llm_stats.py`
- Test: `tests/test_llm_stats.py`

- [ ] **Step 7.1: 写失败测试**

追加到 `tests/test_llm_stats.py`：

```python
import datetime as dt


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
    assert result[0]["cost_usd"] is None  # 全 null → 聚合为 null


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
```

- [ ] **Step 7.2: 跑测试确认失败**

Run: `pytest tests/test_llm_stats.py -v -k 'parse or apply or aggregate'`
Expected: 13 fail with `AttributeError`

- [ ] **Step 7.3: 实现查询 helpers**

追加到 `cli/llm_stats.py`：

```python
import datetime as dt
import re
from collections import defaultdict


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
    """Translate filter key alias to actual record key."""
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
```

- [ ] **Step 7.4: 跑测试确认通过**

Run: `pytest tests/test_llm_stats.py -v`
Expected: 17 passed (4 from Task 6 + 13 new)

- [ ] **Step 7.5: Commit**

```bash
git add cli/llm_stats.py tests/test_llm_stats.py
git commit -m "$(cat <<'EOF'
feat(cli): llm-stats — since / filter / aggregate 查询能力

Why: 排查 SiliconFlow 异常烧钱需要按 provider / caller / 时间窗口聚合查询。
What:
- _parse_since 支持 1h / 24h / 7d / 30m / ISO
- _parse_filter 支持 key=val 精确、key~val 子串、可叠加
- _apply_since / _apply_filters 流式过滤
- _aggregate 按多键 group by，cost null 安全聚合
- caller 别名到 caller_script，让 CLI 更友好
- 13 个单测覆盖各种边界
EOF
)"
```

---

## Task 8: `cli/llm_stats.py` — 输出格式 + argparse

**Files:**
- Modify: `cli/llm_stats.py`
- Test: `tests/test_llm_stats.py`

- [ ] **Step 8.1: 写失败测试**

追加到 `tests/test_llm_stats.py`：

```python
def test_format_table_basic():
    from cli import llm_stats
    rows = [
        {"provider": "openai", "calls": 10, "cost_usd": 1.234},
        {"provider": "anthropic", "calls": 5, "cost_usd": None},
    ]
    out = llm_stats._format_table(rows, ["provider", "calls", "cost_usd"])
    assert "openai" in out
    assert "anthropic" in out
    assert "1.234" in out or "1.23" in out
    assert "null" in out or "-" in out  # null 表示


def test_format_table_empty():
    from cli import llm_stats
    out = llm_stats._format_table([], ["provider", "calls"])
    assert "no data" in out.lower() or out.strip() == ""


def test_main_paths(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    _write_jsonl(tmp_path / "host.jsonl", [_sample(), _sample()])

    import importlib
    from cli import llm_stats
    importlib.reload(llm_stats)
    rc = llm_stats.main(["--paths"])
    out = capsys.readouterr().out
    assert str(tmp_path) in out
    assert "host.jsonl" in out
    assert "2" in out  # line count
    assert rc == 0


def test_main_raw(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    _write_jsonl(tmp_path / "host.jsonl", [_sample(provider="openai")])

    import importlib
    from cli import llm_stats
    importlib.reload(llm_stats)
    rc = llm_stats.main(["--raw"])
    out = capsys.readouterr().out
    parsed = json.loads(out.strip().splitlines()[0])
    assert parsed["provider"] == "openai"
    assert rc == 0


def test_main_tail(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    _write_jsonl(tmp_path / "host.jsonl",
                 [_sample(ts=f"2026-04-20T0{i}:00:00.000Z") for i in range(5)])

    import importlib
    from cli import llm_stats
    importlib.reload(llm_stats)
    rc = llm_stats.main(["--tail", "2", "--raw"])
    out = capsys.readouterr().out
    lines = out.strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["ts"] == "2026-04-20T04:00:00.000Z"
    assert rc == 0


def test_main_filter_provider(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    _write_jsonl(tmp_path / "host.jsonl", [
        _sample(provider="siliconflow", caller="/work/runaway.py"),
        _sample(provider="openai", caller="/work/other.py"),
    ])

    import importlib
    from cli import llm_stats
    importlib.reload(llm_stats)
    rc = llm_stats.main(["--filter", "provider=siliconflow", "--by", "caller", "--raw"])
    out = capsys.readouterr().out
    assert "runaway" in out
    assert "other.py" not in out
    assert rc == 0


def test_main_no_data(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LLM_USAGE_DIR", str(tmp_path))
    import importlib
    from cli import llm_stats
    importlib.reload(llm_stats)
    rc = llm_stats.main([])
    out = capsys.readouterr().out
    assert "no" in out.lower() or "empty" in out.lower() or "0" in out
    assert rc == 0
```

- [ ] **Step 8.2: 跑测试确认失败**

Run: `pytest tests/test_llm_stats.py -v -k 'format_table or main_'`
Expected: 7 fail

- [ ] **Step 8.3: 实现 `_format_table`、`main` 与 argparse**

追加到 `cli/llm_stats.py`：

```python
import argparse


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
        n_lines = sum(1 for _ in open(f, "r", encoding="utf-8"))
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
```

- [ ] **Step 8.4: 跑全部测试**

Run: `pytest tests/test_llm_stats.py -v`
Expected: 24 passed (4 + 13 + 7)

- [ ] **Step 8.5: Commit**

```bash
git add cli/llm_stats.py tests/test_llm_stats.py
git commit -m "$(cat <<'EOF'
feat(cli): llm-stats — 表格输出 + argparse 主入口

Why: 把前面的 helper 串成可用 CLI；--paths / --raw / --tail / --filter / --by 全打通。
What:
- _format_table 自实现对齐输出，零依赖
- _print_summary / _print_paths 文本输出
- main(argv) 走 argparse，支持 7 种调用模式
- 7 个端到端测试覆盖 paths / raw / tail / filter / 空数据
EOF
)"
```

---

## Task 9: `pyproject.toml` — 注册 console script + 子包

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 9.1: 修改 pyproject.toml**

替换：

```toml
[tool.setuptools]
py-modules = ["model_connector", "video_connector", "gemini_uploader"]
```

为：

```toml
[tool.setuptools]
py-modules = ["model_connector", "video_connector", "gemini_uploader", "usage_log"]
packages = ["cli"]
```

在 `[project.optional-dependencies]` 之后追加：

```toml
[project.scripts]
llm-stats = "cli.llm_stats:main"
```

- [ ] **Step 9.2: 重新安装并验证 console script**

```bash
pip install -e . 2>&1 | tail -5
which llm-stats
llm-stats --help
```

Expected: `which llm-stats` 输出虚拟环境内的可执行路径；`--help` 打印 argparse 帮助。

- [ ] **Step 9.3: 跑全部测试**

```bash
pytest tests/ -v
```

Expected: 全部通过（连 `test_connector.py` 旧用例一起）。

- [ ] **Step 9.4: Commit**

```bash
git add pyproject.toml
git commit -m "$(cat <<'EOF'
build: 把 usage_log + cli 子包打进发行清单，注册 llm-stats

Why: 让消费方装完 model_api_connection 后能直接用 llm-stats 命令。
What:
- py-modules 追加 usage_log
- 新增 packages = ["cli"]
- [project.scripts] llm-stats = "cli.llm_stats:main"
EOF
)"
```

---

## Task 10: `README.md` — 加"LLM 用量监控"章节

**Files:**
- Modify: `README.md`

- [ ] **Step 10.1: 读 README 找好插入位置**

```bash
grep -n '^##' README.md
```

确定要插在哪个章节后（通常在"使用方法"之后、"配置"之前）。

- [ ] **Step 10.2: 追加章节**

在合适位置插入：

```markdown
## LLM 用量监控

每次 `chat()` 自动写入一行 JSON 到本机的 `<hostname>.jsonl`（4 台 Mac 通过 iCloud 同步）。
用 `llm-stats` 命令跨机器聚合查询。

### 默认路径

```
~/Library/Mobile Documents/iCloud~md~obsidian/Documents/llm-usage/<hostname>.jsonl
```

通过 `LLM_USAGE_DIR` 环境变量可覆盖（CI / 不用 iCloud 的机器）。

### 给 cron / launchd 任务署名

无人值守任务请设 `LLM_CALLER`，便于事后追溯：

```bash
LLM_CALLER=daily-summary python ~/scripts/daily.py
```

否则日志里 `caller_script` 字段记的是 `sys.argv[0]`，cron 场景下可能不易识别。

### 临时记录 prompt + completion

调试某次怪输出时：

```bash
LLM_LOG_PAYLOAD=1 python ~/scripts/repro.py
llm-stats --tail 1 --raw | jq '.prompt, .completion'
```

默认**不存** prompt / completion，避免泄漏与膨胀。

### 查询示例

```bash
llm-stats                                            # 最近 24h，按 provider 聚合
llm-stats --since 1h --by caller                     # 最近 1h，按 caller 聚合
llm-stats --since 7d --by host                       # 最近一周，按机器聚合
llm-stats --filter provider=siliconflow --since 36h  # 排查异常 provider
llm-stats --filter caller~runaway --raw              # 看具体调用
llm-stats --tail 50                                  # 最近 50 条原始记录
llm-stats --paths                                    # 打印日志目录与各文件状态
```

### 多项目接入

任何项目装好本仓库（`uv add --editable ~/workspace/model_api_connection` 或
`pip install -e ~/workspace/model_api_connection`）后，`from model_connector import chat`
即自动启用日志，**无需任何配置**。建议在消费项目的 CLAUDE.md 加一段：

> ## LLM 调用
> 用 `from model_connector import chat`。所有调用自动记录到本机 iCloud 同步的
> `llm-usage/`，可在任意机器跑 `llm-stats` 查询。
> cron / 长期脚本请设 `LLM_CALLER=<task-name>` 便于事后追溯。
```

- [ ] **Step 10.3: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(readme): 新增 "LLM 用量监控" 章节

Why: 让用户和消费方项目知道日志在哪、怎么查、怎么署名。
What:
- 默认路径 + LLM_USAGE_DIR 覆盖说明
- LLM_CALLER 用于 cron/launchd 署名
- LLM_LOG_PAYLOAD=1 临时开 prompt/completion
- 7 个常用 llm-stats 查询示例
- 多项目接入提示 + 推荐 CLAUDE.md 模板
EOF
)"
```

---

## Task 11: 端到端手动验收

**Files:** 无修改，只跑命令验证。

- [ ] **Step 11.1: 装新版本到当前 venv**

```bash
pip install -e . 2>&1 | tail -3
```

Expected: `Successfully installed model-api-connection-0.1.0`。

- [ ] **Step 11.2: 跑一次真实 chat()**

```bash
cd /tmp
python -c "from model_connector import chat; print(chat('ping', provider='openai'))"
```

Expected: 收到模型回复。

- [ ] **Step 11.3: 验证 jsonl 行写入 + 权限**

```bash
F="$HOME/Library/Mobile Documents/iCloud~md~obsidian/Documents/llm-usage/$(hostname).jsonl"
ls -l "$F"
tail -1 "$F" | python -c "import json,sys; r=json.load(sys.stdin); print(r['provider'], r['model'], r['cost_usd'], r['caller_script'])"
```

Expected:
- `-rw-------` 权限位 (0600)
- 输出含 `openai`、模型 id、cost、caller 路径

- [ ] **Step 11.4: 验证 LLM_CALLER 覆盖**

```bash
LLM_CALLER=manual-test python -c "from model_connector import chat; chat('ping', provider='openai')"
tail -1 "$F" | python -c "import json,sys; print(json.load(sys.stdin)['caller_script'])"
```

Expected: 输出 `manual-test`。

- [ ] **Step 11.5: 验证 LLM_LOG_PAYLOAD**

```bash
LLM_LOG_PAYLOAD=1 python -c "from model_connector import chat; chat('say hi', provider='openai')"
tail -1 "$F" | python -c "import json,sys; r=json.load(sys.stdin); print('prompt' in r, 'completion' in r)"
```

Expected: `True True`。

- [ ] **Step 11.6: 验证失败也写入**

```bash
python -c "from model_connector import chat; chat('hi', provider='openai', model='this-model-does-not-exist')" 2>/dev/null || true
tail -1 "$F" | python -c "import json,sys; r=json.load(sys.stdin); print(r['status'], r['error'][:60])"
```

Expected: `error <some message>`。

- [ ] **Step 11.7: 验证写失败时 chat 仍然返回**

```bash
LLM_USAGE_DIR=/dev/null/cannot-write python -c "from model_connector import chat; print(chat('ping', provider='openai'))" 2>&1 | tail -5
```

Expected: chat 返回回复；stderr 有 `[usage_log] WARN:` 一行。

- [ ] **Step 11.8: 跑 llm-stats 各模式**

```bash
llm-stats --since 1h
llm-stats --since 1h --by caller
llm-stats --since 1h --filter provider=openai --raw
llm-stats --tail 5
llm-stats --paths
```

Expected: 输出符合预期；都没崩。

- [ ] **Step 11.9: 在第二台 Mac 上重复 11.1-11.3**

等 iCloud 同步几分钟后，回到第一台 Mac：

```bash
llm-stats --since 1h --by host
```

Expected: 看到两台机器的 host 都有调用计数。

- [ ] **Step 11.10: 完成 PR**

```bash
git push -u origin feat/usage-logging-spec
gh pr create --title "feat: LLM 用量自动记录 + llm-stats CLI" --body "$(cat <<'EOF'
## Summary
- litellm callback 自动记录每次 chat() 到 ~/<iCloud>/llm-usage/<host>.jsonl
- llm-stats CLI 跨机器聚合查询（since / by / filter / raw / tail / paths）
- 多项目接入零侵入
- 与 1P 密钥同步、singleton/raw 修复正交独立

## Spec / Plan
- spec: docs/superpowers/specs/2026-04-20-llm-usage-logging-design.md
- plan: docs/superpowers/plans/2026-04-20-llm-usage-logging.md

## Test plan
- [ ] pytest tests/ 全绿
- [ ] 在 4 台 Mac 上 pip install -e . 后跑场景 A-E
- [ ] 等 iCloud 同步后验证 llm-stats --by host 跨机器汇总
- [ ] SiliconFlow 异常溯源场景：llm-stats --filter provider=siliconflow --since 36h --by caller
EOF
)"
```

---

## 与其他 PR 的协作

| PR | branch | 与本 PR 的冲突点 | 解决 |
|----|--------|-----------------|------|
| 1P 密钥同步 | `refactor/1p-key-sync` | `model_connector.py` import 段、`pyproject.toml`、`README.md` | 任意顺序合，最多一个 import 顺序 conflict 手动 resolve |
| singleton + raw=True | 待开 | `model_connector.py` chat()/get_connector() 函数体 | 与本 PR 在 `chat()` 内的 metadata 注入有交叉，注意保留 `metadata` 透传 |

如果 1P 或 singleton/raw 在本 PR 之前合入，rebase `feat/usage-logging-spec` 时遵循：
- 保留两边对 `model_connector.py` 顶部的 import 追加
- 保留 `chat()` 内 `metadata` 字段
- `pyproject.toml` 是 toml dict，merge 时把两边新增的 section 都保留
