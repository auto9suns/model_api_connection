# Connector Singleton + `chat(raw=True)` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修 `get_connector()` 的单例覆盖 bug；给 `chat()` 增加 `raw=True` 参数让调用者拿完整 litellm response。

**Architecture:** 两个独立小改，全部局限在 `model_connector.py` 一个文件 + `tests/test_connector.py` 一个文件。无新依赖，无新模块。

**Tech Stack:** Python 3.10+, litellm, pytest（已有）。

**Spec:** `docs/superpowers/specs/2026-04-20-connector-singleton-and-raw-design.md`

---

## File Structure

| 文件 | 责任 | 是否新建 |
|------|------|----------|
| `model_connector.py` | 修 `get_connector`、给 `chat()` 加 `raw=True` | 修改 |
| `tests/test_connector.py` | 追加 9 个新测试（4 singleton + 5 raw） | 修改 |

---

## Task 1: `get_connector()` singleton 修复（TDD）

**Files:**
- Modify: `model_connector.py:184-192`
- Test: `tests/test_connector.py`

- [ ] **Step 1.1: 写失败测试**

追加到 `tests/test_connector.py` 末尾：

```python
# ── get_connector singleton tests ─────────────────────────────────────────────

import importlib


def _reset_connector_module():
    """Reset the module-level singleton between tests."""
    import model_connector as mc
    mc._default_connector = None


def test_get_connector_no_kwargs_returns_singleton():
    _reset_connector_module()
    import model_connector as mc
    a = mc.get_connector()
    b = mc.get_connector()
    assert a is b


def test_get_connector_with_kwargs_returns_fresh():
    _reset_connector_module()
    import model_connector as mc
    a = mc.get_connector()
    b = mc.get_connector(api_keys={"openai": "tmp-key"})
    assert a is not b


def test_get_connector_with_kwargs_preserves_singleton():
    """Regression test: passing kwargs must NOT overwrite the singleton."""
    _reset_connector_module()
    import model_connector as mc
    default = mc.get_connector()
    _ = mc.get_connector(api_keys={"openai": "tmp-key"})
    again = mc.get_connector()
    assert again is default


def test_get_connector_first_call_with_kwargs_does_not_pollute():
    """First-ever call with kwargs returns a fresh instance and leaves singleton uninitialized."""
    _reset_connector_module()
    import model_connector as mc
    one_off = mc.get_connector(api_keys={"openai": "x"})
    assert mc._default_connector is None
    default = mc.get_connector()
    assert default is not one_off
```

- [ ] **Step 1.2: 跑测试确认失败**

Run: `cd $WORKSPACE_ROOT/model_api_connection && pytest tests/test_connector.py -v -k get_connector`
Expected:
- `test_get_connector_no_kwargs_returns_singleton` PASS
- `test_get_connector_with_kwargs_returns_fresh` PASS
- `test_get_connector_with_kwargs_preserves_singleton` **FAIL**
- `test_get_connector_first_call_with_kwargs_does_not_pollute` **FAIL**

- [ ] **Step 1.3: 修 `get_connector`**

替换 `model_connector.py:187-192`：

```python
def get_connector(**kwargs) -> LLMConnector:
    """Return the module-level singleton if no kwargs; otherwise return a
    fresh one-off instance (without touching the singleton)."""
    if kwargs:
        return LLMConnector(**kwargs)
    global _default_connector
    if _default_connector is None:
        _default_connector = LLMConnector()
    return _default_connector
```

- [ ] **Step 1.4: 跑测试确认 4 个全过**

Run: `pytest tests/test_connector.py -v -k get_connector`
Expected: 4 passed

- [ ] **Step 1.5: 跑全集回归**

Run: `pytest tests/ -v`
Expected: 全部通过（既有 + 新增）

- [ ] **Step 1.6: Commit**

```bash
git add model_connector.py tests/test_connector.py
git commit -m "$(cat <<'EOF'
fix(connector): get_connector(**kwargs) 不再覆盖单例

Why: 之前 `if _default_connector is None or kwargs:` 这行让"传 kwargs 取
临时实例"的调用静默把全局单例换掉，后续无参 get_connector() 拿到的是
临时实例而非默认实例——污染影响范围未知且难以察觉。
What:
- model_connector.py: 区分两条路径——传 kwargs 直接 new 不缓存；
  无 kwargs 走 lazy 单例
- tests/test_connector.py: 4 个用例（含关键回归 preserves_singleton）
EOF
)"
```

---

## Task 2: `chat(raw=True)` 非流（TDD）

**Files:**
- Modify: `model_connector.py:79-127` (LLMConnector.chat)
- Test: `tests/test_connector.py`

- [ ] **Step 2.1: 写失败测试**

追加到 `tests/test_connector.py`：

```python
# ── chat(raw=True) tests ──────────────────────────────────────────────────────

def test_chat_raw_returns_full_response(connector):
    """raw=True returns the litellm ModelResponse object as-is."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Hello!"
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 5

    with patch("model_connector.litellm.completion", return_value=mock_response):
        result = connector.chat("Hi", provider="openai", raw=True)
    assert result is mock_response
    assert result.usage.prompt_tokens == 10


def test_chat_raw_default_returns_string(connector):
    """raw=False (default) keeps existing behavior — return text only."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = "Hello!"

    with patch("model_connector.litellm.completion", return_value=mock_response):
        result = connector.chat("Hi", provider="openai")
    assert result == "Hello!"


def test_chat_raw_preserves_tool_calls(connector):
    """raw=True lets caller see tool_calls when content is None."""
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = None
    fake_tc = [{"id": "call_1", "function": {"name": "get_weather"}}]
    mock_response.choices[0].message.tool_calls = fake_tc

    with patch("model_connector.litellm.completion", return_value=mock_response):
        result = connector.chat("北京天气", provider="openai", raw=True)
    assert result.choices[0].message.tool_calls == fake_tc
```

- [ ] **Step 2.2: 跑测试确认失败**

Run: `pytest tests/test_connector.py -v -k 'chat_raw'`
Expected: 3 fail with `TypeError: chat() got an unexpected keyword argument 'raw'`

- [ ] **Step 2.3: 改 `LLMConnector.chat` 加 `raw`**

替换 `model_connector.py:79-127`（整个 chat 方法）：

```python
def chat(
    self,
    messages: str | list[dict],
    *,
    provider: str,
    model: str | None = None,
    stream: bool = False,
    raw: bool = False,
    **kwargs,
) -> str | Iterator[str]:
    """
    Send a chat request via litellm.

    Parameters
    ----------
    messages : str or list of dicts
        Plain string, or full message list:
        [{"role": "user"|"assistant"|"system", "content": "..."}]
    provider : str
        Provider key from models_config.json.
    model : str, optional
        Model alias as listed in models_config.json.
        Uses the provider's default_model if omitted.
    stream : bool
        Return a chunk iterator instead of a full result.
    raw : bool, default False
        If False (default): non-stream returns str, stream returns str chunks.
        If True: non-stream returns the litellm ModelResponse; stream returns
        the raw chunk iterator from litellm.completion(stream=True).
    **kwargs
        Forwarded to litellm.completion (temperature, max_tokens, tools, etc.).
    """
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]

    prov_cfg = self._get_provider_config(provider)
    model_id = self._resolve_model(prov_cfg, model)
    api_key = self._get_api_key(provider, prov_cfg)

    litellm_kwargs = {
        "model": model_id,
        "messages": messages,
        "stream": stream,
        "api_key": api_key,
        **kwargs,
    }
    if "base_url" in prov_cfg:
        litellm_kwargs["api_base"] = prov_cfg["base_url"]

    response = litellm.completion(**litellm_kwargs)

    if stream:
        if raw:
            return response
        return self._iter_stream(response)
    if raw:
        return response
    return response.choices[0].message.content
```

- [ ] **Step 2.4: 跑测试确认 3 个新增 + 既有非流用例都过**

Run: `pytest tests/test_connector.py -v -k 'chat'`
Expected: 全部通过（含原有 `test_string_message_wrapped` / `test_chat_passes_api_base_for_custom_provider` / `test_chat_with_tools` / `test_chat_streaming` 不动）

- [ ] **Step 2.5: Commit**

```bash
git add model_connector.py tests/test_connector.py
git commit -m "$(cat <<'EOF'
feat(connector): chat() 新增 raw=True 参数

Why: tool_calls / usage / finish_reason 等字段被现有 chat() 吞掉；
function calling 时 content 是 None 直接返回 None，调用者拿不到 tool_calls。
What:
- LLMConnector.chat 新增 raw 参数
  - raw=False（默认）保持原行为（返回 str / str iterator）
  - raw=True 非流返回 ModelResponse，流返回原始 chunk iterator
- tests: 3 个新用例覆盖 raw 行为 + 现有用例验证回归
EOF
)"
```

---

## Task 3: `chat(raw=True)` 流式 + 模块级 shortcut（TDD）

**Files:**
- Modify: `model_connector.py:195-204` (module-level `chat`)
- Test: `tests/test_connector.py`

- [ ] **Step 3.1: 写失败测试（流 + 模块级）**

追加到 `tests/test_connector.py`：

```python
def test_chat_raw_stream_returns_raw_iterator(connector):
    """stream=True + raw=True returns the litellm chunk iterator unchanged."""
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta.content = "Hello"
    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta.content = " world"
    raw_iter = iter([chunk1, chunk2])

    with patch("model_connector.litellm.completion", return_value=raw_iter):
        result = connector.chat("Hi", provider="openai", stream=True, raw=True)
    chunks = list(result)
    assert chunks == [chunk1, chunk2]


def test_chat_raw_stream_default_returns_text_iterator(connector):
    """stream=True + raw=False (default) returns text chunks (regression)."""
    chunk1 = MagicMock()
    chunk1.choices = [MagicMock()]
    chunk1.choices[0].delta.content = "Hello"
    chunk2 = MagicMock()
    chunk2.choices = [MagicMock()]
    chunk2.choices[0].delta.content = " world"
    raw_iter = iter([chunk1, chunk2])

    with patch("model_connector.litellm.completion", return_value=raw_iter):
        result = connector.chat("Hi", provider="openai", stream=True)
    assert list(result) == ["Hello", " world"]


def test_module_chat_shortcut_passes_raw(connector, monkeypatch):
    """Module-level chat() must forward raw=True down to the singleton."""
    _reset_connector_module()
    import model_connector as mc

    captured = {}

    def fake_chat(self, messages, *, provider, model=None, stream=False, raw=False, **kwargs):
        captured["raw"] = raw
        captured["stream"] = stream
        return "ok"

    monkeypatch.setattr(mc.LLMConnector, "chat", fake_chat)
    mc.chat("hi", provider="openai", raw=True)
    assert captured["raw"] is True
```

- [ ] **Step 3.2: 跑测试确认失败**

Run: `pytest tests/test_connector.py -v -k 'raw_stream or module_chat'`
Expected:
- `test_chat_raw_stream_returns_raw_iterator` PASS（Task 2 已实现这条）
- `test_chat_raw_stream_default_returns_text_iterator` PASS
- `test_module_chat_shortcut_passes_raw` **FAIL**（模块级 chat 还没透传 raw）

- [ ] **Step 3.3: 改模块级 `chat` shortcut**

替换 `model_connector.py:195-204`：

```python
def chat(
    messages: str | list[dict],
    *,
    provider: str,
    model: str | None = None,
    stream: bool = False,
    raw: bool = False,
    **kwargs,
) -> str | Iterator[str]:
    """Module-level shortcut — no need to instantiate LLMConnector."""
    return get_connector().chat(
        messages,
        provider=provider,
        model=model,
        stream=stream,
        raw=raw,
        **kwargs,
    )
```

- [ ] **Step 3.4: 跑测试确认全过**

Run: `pytest tests/test_connector.py -v`
Expected: 全部通过

- [ ] **Step 3.5: Commit**

```bash
git add model_connector.py tests/test_connector.py
git commit -m "$(cat <<'EOF'
feat(connector): 模块级 chat() shortcut 同步透传 raw 参数

Why: LLMConnector.chat 已支持 raw，但模块级 chat() 没透传，调用者
被迫绕一层 get_connector().chat(...)。
What:
- 模块级 chat 加 raw 参数，原样转给 connector 实例
- tests: 模块级 raw 透传 + stream+raw 流式回归测试
EOF
)"
```

---

## Task 4: 全集回归 + PR

**Files:** 无修改。

- [ ] **Step 4.1: 全集回归**

```bash
pytest tests/ -v
```

Expected: 全部通过，无 regression。

- [ ] **Step 4.2: 推 + 开 PR**

```bash
git push -u origin fix/connector-singleton-and-raw
gh pr create --title "fix: get_connector singleton bug + chat(raw=True) 支持" --body "$(cat <<'EOF'
## Summary
- 修 `get_connector(**kwargs)` 静默覆盖单例的 bug
- `chat()` 新增 `raw=True` 参数，让调用者拿完整 litellm response（含 usage / tool_calls / finish_reason）
- 默认行为 100% 保持，所有现有调用方零改动

## Spec / Plan
- spec: docs/superpowers/specs/2026-04-20-connector-singleton-and-raw-design.md
- plan: docs/superpowers/plans/2026-04-20-connector-singleton-and-raw.md

## Test plan
- [ ] pytest tests/test_connector.py 全绿（含 9 个新增）
- [ ] 全集 pytest tests/ 全绿
- [ ] 现有 chat() / chat(stream=True) caller 行为不变
EOF
)"
```

---

## 与其他 PR 的协作

| PR | branch | 与本 PR 的冲突点 | 解决 |
|----|--------|-----------------|------|
| 1P 密钥同步 | `refactor/1p-key-sync` | `model_connector.py` 顶部 import + `_get_api_key` 错误信息 | 本 PR 不动这两处，可以无冲突 |
| usage-logging | `feat/usage-logging-spec` | `model_connector.py` 顶部 import 段 + `chat()` 内 `metadata` 字段 | usage-logging 在 `litellm_kwargs` 加 `metadata`；本 PR 也碰 `chat()` 函数体 → **会有 merge conflict**。建议合入顺序：usage-logging 先合，本 PR rebase 时把 `metadata` 字段保留即可 |

如果本 PR 先合：usage-logging rebase 时，把 `metadata` 字段加到 `litellm_kwargs` dict、把 `register()` 加到 import 段——两者都不动 `raw=` 参数和 singleton 修复。
