# Model API Connection — `get_connector` singleton 修复 + `chat(raw=True)`

**日期**：2026-04-20
**状态**：已 approve（brainstorm 阶段）
**负责人**：xuche

---

## 1. 问题

`model_connector.py` 有两个独立的小问题，原本散落在 1P 密钥同步 spec 里，现已剥离独立处理：

### 1.1 `get_connector()` singleton 被静默覆盖

当前实现（`model_connector.py:184-192`）：

```python
_default_connector: LLMConnector | None = None

def get_connector(**kwargs) -> LLMConnector:
    global _default_connector
    if _default_connector is None or kwargs:
        _default_connector = LLMConnector(**kwargs)
    return _default_connector
```

**Bug**：调用者若想要"临时一次性 connector"，传 `kwargs` 进去，**会把模块级单例 `_default_connector` 覆盖掉**。后续任何 `get_connector()`（无参数）调用都拿到这个被改过的实例——而不是预期的"默认实例"。

具体的踩坑场景：

```python
# 默认实例已被建好
get_connector()                                       # → 默认 connector A

# 想用临时 key 跑一次
get_connector(api_keys={"openai": "tmp-key"})         # → 新 connector B（把 A 覆盖）

# 期望：拿回 A
get_connector()                                       # → 实际拿到 B（带着临时 key）
```

后续所有 chat() 都用了临时 key，没人知道。

### 1.2 `chat()` 只能拿到文本，拿不到完整 response

当前 `chat()` 只返回 `response.choices[0].message.content`（`model_connector.py:127`）。Caller 拿不到：
- `response.usage`（token 计数）
- `response.choices[0].finish_reason`
- `response.choices[0].message.tool_calls`（function calling 结果）
- 任何 provider 特定的 metadata

**踩坑场景**：调用 function calling 时，模型返回 `tool_calls` 但 `content` 是 `None`。当前的 chat() 直接返回 `None`，调用者无法拿到 tool_calls。

## 2. 目标

- `get_connector(**kwargs)` 行为符合直觉：传参数就给临时实例，不污染单例。
- `chat(..., raw=True)` 返回完整 response 对象（非流）/ 完整 chunk 迭代器（流）。
- `raw=False` 是默认值，**完全保留现有行为**，所有现有 caller 零改动。
- 公共 API（`__all__`）不变，`raw=True` 只是新参数。

## 3. Non-Goals

- 不重构 `LLMConnector` 类的其他部分。
- 不引入新的依赖。
- 不动 `chat()` 的其他参数语义（`stream` / `tools` / `messages` 等照旧）。
- 不动密钥加载（那块属于 1P PR）。
- 不动 callback 机制（那块属于 usage-logging PR）。
- 不为 `raw=True` 提供任何"标准化封装"——直接透传 litellm 原始对象，由调用者决定如何用。

## 4. 改动 1：`get_connector()` 修复

### 当前

```python
def get_connector(**kwargs) -> LLMConnector:
    global _default_connector
    if _default_connector is None or kwargs:
        _default_connector = LLMConnector(**kwargs)
    return _default_connector
```

### 修复后

```python
def get_connector(**kwargs) -> LLMConnector:
    """Return the module-level singleton if no kwargs; otherwise return a fresh
    one-off instance (without touching the singleton)."""
    if kwargs:
        return LLMConnector(**kwargs)
    global _default_connector
    if _default_connector is None:
        _default_connector = LLMConnector()
    return _default_connector
```

### 行为对比

| 调用 | 修复前 | 修复后 |
|------|--------|--------|
| `get_connector()` × N（无参数） | 同一个单例 | 同一个单例（不变） |
| `get_connector(api_keys=...)` | **覆盖单例**，返回新实例 | 返回新实例，**不动单例** |
| 之后再 `get_connector()` | 拿到被覆盖的实例（bug） | 拿到原单例（修复） |

### 向后兼容性

- 如果之前有人**故意**利用"传 kwargs 来重建单例"的语义—— 几乎不可能，因为这个 bug 没有显式 API 声明，纯是 `if kwargs:` 这一行的副作用。`__all__` 没声明、README 没写、tests 也没覆盖。视为**纯 bug**。

## 5. 改动 2：`chat(raw=True)`

### 当前

```python
def chat(
    self,
    messages,
    *,
    provider: str,
    model=None,
    stream=False,
    **kwargs,
):
    ...
    response = litellm.completion(**litellm_kwargs)
    if stream:
        return self._iter_stream(response)
    return response.choices[0].message.content
```

### 修改后

```python
def chat(
    self,
    messages,
    *,
    provider: str,
    model=None,
    stream=False,
    raw=False,
    **kwargs,
):
    """
    Send a chat request via litellm.

    Parameters
    ----------
    raw : bool, default False
        - False (默认): 非流返回 str，流返回 str chunk 迭代器（向后兼容）。
        - True: 非流返回 litellm 原始 ModelResponse；流返回原始 chunk 迭代器
          （chunks 直接来自 litellm.completion(stream=True)，未做 .delta.content 抽取）。
    """
    ...
    response = litellm.completion(**litellm_kwargs)
    if stream:
        if raw:
            return response  # 原始 chunk 迭代器
        return self._iter_stream(response)
    if raw:
        return response  # 完整 ModelResponse 对象
    return response.choices[0].message.content
```

### 行为对比

| 调用 | 返回类型 | 用途 |
|------|---------|------|
| `chat(...)` | `str` | 现有用法，零改动 |
| `chat(..., stream=True)` | `Iterator[str]` | 现有用法，零改动 |
| `chat(..., raw=True)` | `ModelResponse` | 拿 `.usage` / `.choices[0].message.tool_calls` / `.finish_reason` |
| `chat(..., raw=True, stream=True)` | `Iterator[ModelChunk]` | 流式拿原始 chunk（含 reasoning 字段、tool_calls 增量等） |

### 模块级 `chat()` shortcut 同步加 `raw` 参数

```python
def chat(
    messages,
    *,
    provider,
    model=None,
    stream=False,
    raw=False,
    **kwargs,
):
    return get_connector().chat(
        messages, provider=provider, model=model,
        stream=stream, raw=raw, **kwargs,
    )
```

## 6. 错误处理

| 场景 | 行为 |
|------|------|
| `raw=True` 时 litellm 抛异常 | 原样向上抛（与 `raw=False` 相同行为） |
| `raw=True` + `stream=True` 时遍历过程中 chunk 出错 | 原样抛（litellm 自身的 chunk 行为） |
| `get_connector(unknown_kwarg=...)` | `LLMConnector.__init__` 抛 `TypeError`（不变） |

不引入新异常类，不静默吞错。

## 7. 测试

新增 `tests/test_connector.py` 用例：

### singleton 修复

- `test_get_connector_no_kwargs_returns_singleton`：连续无参 call 返回同一对象（`is` 判等）。
- `test_get_connector_with_kwargs_returns_fresh`：传 kwargs 返回新实例（`is not`）。
- `test_get_connector_with_kwargs_preserves_singleton`：传 kwargs 后再无参 call，仍是原单例（关键回归测试，覆盖 bug 场景）。
- `test_get_connector_first_call_with_kwargs_does_not_pollute`：模块刚加载时，第一次就传 kwargs，singleton 仍未被设置；下一次无参 call 才创建默认单例。

### `raw=True`

- `test_chat_raw_returns_full_response`：非流 + raw=True 返回 mock 的 ModelResponse 对象（`is` 判等）。
- `test_chat_raw_default_returns_string`：raw=False（默认）返回 `.choices[0].message.content` 字符串（回归保护）。
- `test_chat_raw_stream_returns_raw_iterator`：流 + raw=True 返回原始 chunk 迭代器（不走 `_iter_stream`）。
- `test_chat_raw_stream_default_returns_text_iterator`：流 + raw=False 返回 `_iter_stream` 抽出来的文本迭代器（回归保护）。
- `test_module_chat_shortcut_passes_raw`：模块级 `chat(raw=True)` 透传到 connector 实例。

`tests/test_connector.py` 现有用例全部保留，验证回归。

## 8. 迁移计划

1. 写 `tests/test_connector.py` 4 个 singleton 测试 → 跑确认 3 个失败 / 1 个 (pollute) 失败 → 修 `get_connector` → 跑全绿 → commit。
2. 写 5 个 `raw=True` 测试 → 跑确认全失败 → 改 `LLMConnector.chat()` 加 `raw` 参数 → 跑全绿 → commit。
3. 改模块级 `chat()` shortcut 加 `raw` → 跑全绿 → commit。
4. 跑 `pytest tests/` 全集 → 确认所有现有用例还过 → 提 PR。

## 9. 验收标准

- 现有 `pytest tests/test_connector.py` 全部通过（zero regression）。
- 新增 9 个测试通过。
- `chat()` 在 `raw=False` 时返回值类型与改动前**完全一致**。
- 故意打破 singleton 的回归测试通过：`get_connector(api_keys={...})` 后 `get_connector()` 仍返回原默认实例。
- 公共 API（`__all__` = `["LLMConnector", "chat", "get_connector", "strip_think_stream"]`）字面量不变。
- 不引入新依赖。

## 10. 范围外

- **1Password 密钥同步** → `2026-04-19-1p-key-sync-redesign.md`
- **LLM 用量自动记录** → `2026-04-20-llm-usage-logging-design.md`
- 重构 `LLMConnector` 类内部其他方法（无必要）。
- 给 `chat()` 加 streaming 之外的高级特性（async / batching 等）。
