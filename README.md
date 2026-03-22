# LLM API Connector

A lightweight, config-driven Python connector for multiple LLM providers. Import it in any script or tool — one unified interface regardless of provider.

**Supported providers:** OpenAI · Anthropic (Claude) · Google (Gemini) · SiliconFlow

---

## Files

| File | Purpose |
|------|---------|
| `model_connector.py` | Core connector — import this in your scripts |
| `models_config.json` | Model registry (edit here to add/update models) |
| `test_models.py` | Verify API keys and model connectivity |
| `fetch_models.py` | Fetch live model lists from provider APIs |
| `.env.example` | API key template |

---

## Setup

**1. Install dependencies**

```bash
pip install -r requirements.txt
# or manually:
pip install openai anthropic python-dotenv litellm
```

**2. Configure API keys**

```bash
cp .env.example .env
# Edit .env and fill in your keys
```

Or export directly:

```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GEMINI_API_KEY=AIza...
export SILICONFLOW_API_KEY=sf-...
```

---

## Usage

### Basic import

```python
from model_connector import LLMConnector

llm = LLMConnector()

# Single message
response = llm.chat("你好", provider="siliconflow", model="deepseek-v3")

# Use provider default model
response = llm.chat("Hi", provider="openai")
```

### Streaming

```python
for chunk in llm.chat("解释量子纠缠", provider="anthropic", model="sonnet-4.6", stream=True):
    print(chunk, end="", flush=True)
```

### Multi-turn conversation

```python
messages = [
    {"role": "system", "content": "你是简洁的助手。"},
    {"role": "user", "content": "我叫小明"},
    {"role": "assistant", "content": "你好，小明！"},
    {"role": "user", "content": "我叫什么名字？"},
]
response = llm.chat(messages, provider="openai", model="gpt-4o")
```

### Module-level shortcut (no instantiation needed)

```python
from model_connector import chat

response = chat("Hi", provider="gemini", model="gemini-2.0-flash")
```

### Extra API parameters

```python
response = llm.chat("...", provider="openai", model="gpt-4o", temperature=0.2, max_tokens=512)
```

### Reasoning models — filtering `<think>` blocks

Models like **DeepSeek-R1** and **Kimi-K2.5** output a chain-of-thought reasoning process before the final answer. The connector automatically wraps this reasoning in `<think>...</think>` tags in the stream, so callers can detect and handle it consistently.

**Default stream output (reasoning visible):**

```python
for chunk in llm.chat("解释递归", provider="siliconflow", model="deepseek-r1", stream=True):
    print(chunk, end="", flush=True)
# Output: <think>让我思考一下...</think>递归是指函数调用自身...
```

**Strip reasoning from stream** — use this helper to get only the final answer:

```python
def strip_think_stream(chunks):
    """Remove <think>...</think> blocks from a streaming response."""
    OPEN, CLOSE = "<think>", "</think>"
    buf, in_think = "", False
    for chunk in chunks:
        buf += chunk
        out = ""
        while True:
            if in_think:
                idx = buf.find(CLOSE)
                if idx == -1:
                    buf = buf[-(len(CLOSE)-1):] if len(buf) >= len(CLOSE) else buf
                    break
                buf = buf[idx + len(CLOSE):].lstrip("\n")
                in_think = False
            else:
                idx = buf.find(OPEN)
                if idx == -1:
                    tail = len(OPEN) - 1
                    if len(buf) > tail:
                        out += buf[:-tail]
                        buf = buf[-tail:]
                    break
                out += buf[:idx]
                buf = buf[idx + len(OPEN):]
                in_think = True
        if out:
            yield out
    if buf and not in_think:
        yield buf

# Usage
raw = llm.chat("解释递归", provider="siliconflow", model="deepseek-r1", stream=True)
for chunk in strip_think_stream(raw):
    print(chunk, end="", flush=True)
# Output: 递归是指函数调用自身...（无推理过程）
```

**Why `<think>` tags?** The underlying API returns reasoning in a separate `reasoning_content` field (not `content`). The connector wraps it with `<think>...</think>` so every caller sees a single unified text stream and can filter consistently — no need to know about the provider's internal field structure.

---

## Model names

Model keys in `models_config.json` are short and human-readable. Values are the exact official API IDs.

| Provider | Key (what you type) | Value (sent to API) |
|----------|--------------------|--------------------|
| openai | `gpt-4o` | `gpt-4o` |
| openai | `o4-mini` | `o4-mini` |
| anthropic | `sonnet-4.6` | `claude-sonnet-4-6` |
| anthropic | `haiku-4.5` | `claude-haiku-4-5-20251001` |
| gemini | `gemini-2.5-pro` | `gemini-2.5-pro-preview-03-25` |
| siliconflow | `deepseek-v3` | `deepseek-ai/DeepSeek-V3` |
| siliconflow | `qwq-32b` | `Qwen/QwQ-32B` |

You can also pass a raw model ID not yet in the config — it will be forwarded directly:

```python
llm.chat("Hi", provider="openai", model="gpt-5")  # not in config yet, passed through as-is
```

---

## Updating models

When providers release new models, edit `models_config.json`:

```json
"siliconflow": {
  "models": {
    "deepseek-v4": "deepseek-ai/DeepSeek-V4"
  }
}
```

Use `fetch_models.py` to discover new model IDs from the live API.

---

## Scripts

### Test API connectivity

```bash
# Quick check — default model per provider
python test_models.py

# Test all models for one provider
python test_models.py --provider siliconflow --all

# Test a specific model
python test_models.py --provider anthropic --model sonnet-4.6

# Full test across all providers and all models
python test_models.py --all
```

### Fetch live model lists

All runs always show: **Model ID · Age · $/1M (in/out) · Ctx · Flags · Description**

```bash
# All providers — models released in last 6 months
python fetch_models.py

# All models regardless of age
python fetch_models.py --all

# Only models listed in models_config.json (still calls provider API)
python fetch_models.py --current

# One provider
python fetch_models.py --provider openai

# One provider, config models only, all ages
python fetch_models.py --provider anthropic --current --all

# Custom recency window
python fetch_models.py --months 3
```

**Columns:**

| Column | Source | Notes |
|--------|--------|-------|
| Model ID | Provider API | filtered to config models with `--current` |
| Age | API timestamp → name extraction fallback | e.g. `preview-04-17` → Apr 17 |
| `$/1M in/out` | LiteLLM (USD) / siliconflow.cn/pricing (¥ CNY) | `—` if not found |
| `Ctx` | LiteLLM `max_input_tokens` | context window size |
| `Flags` | LiteLLM capability fields | `V`=vision `F`=tools `R`=reasoning `C`=cache `S`=schema |
| Description | `display_name` (Anthropic/Gemini) · LiteLLM mode | e.g. `Claude Sonnet 4.6`, `[chat]` |

**`--current`:** calls the provider API as normal, but filters results to only the model IDs defined in `models_config.json`. Useful for auditing exactly what's configured and its current pricing/capabilities.

---

## Using in other projects

Since the connector and config live in a fixed directory, add this to any script that imports it:

```python
import sys
sys.path.insert(0, "/path/to/model_api_connection")
from model_connector import LLMConnector
```

Or install as an editable package by adding a minimal `pyproject.toml` if needed.
