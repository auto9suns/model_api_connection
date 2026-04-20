# LLM API Connector

轻量级、配置驱动的多模型统一连接器，底层基于 [litellm](https://github.com/BerriAI/litellm)。一次 import，统一调用 OpenAI / Anthropic / Gemini / SiliconFlow / Poe 及任何 OpenAI 兼容 API。

---

## 快速接入（其他项目）

```bash
# 推荐：uv editable install
uv add --editable ~/workspace/model_api_connection
# 或 pip 兜底
pip install -e ~/workspace/model_api_connection
```

```python
from model_connector import chat, LLMConnector, strip_think_stream

# 一句话调用（模块级快捷方式，无需实例化）
response = chat("你好", provider="openai")

# 实例化方式（可自定义 config_path / api_keys）
llm = LLMConnector()
response = llm.chat("你好", provider="openai")
```

---

## 文件结构

| 文件 | 用途 |
|------|------|
| `model_connector.py` | 核心连接器 — 其他项目 import 这个 |
| `paths.py` | 路径常量（API key 缓存目录、config 文件位置） |
| `gemini_uploader.py` | 上传视频到 Gemini File API，等待处理完成，返回 URI |
| `video_connector.py` | 统一视频理解接口，支持 Gemini / Qwen |
| `models_config.json` | 模型注册表（增删模型改这里） |
| `key_sync.py` | CLI 工具：从 1Password 同步 API key 到 `~/.config/llm/keys.env` |
| `test_models.py` | CLI 工具：验证 API key 和模型连通性 |
| `fetch_models.py` | CLI 工具：从 API 拉取最新模型列表 |
| `_fetch_helpers.py` | fetch_models.py 的内部辅助模块 |
| `usage_log.py` | LLM 调用日志底层：路径解析 + JSONL writer + caller 识别 + record builder + litellm callback 注册 |
| `cli/llm_stats.py` | llm-stats CLI：跨机器 JSONL 日志合并读取、时间过滤、字段过滤、多维聚合 |
| `tests/` | 单元测试（`pytest tests/`） |

---

## 安装

**1. 安装包（推荐 uv）**

```bash
# 在消费方项目根目录执行
uv add --editable ~/workspace/model_api_connection
# 或 pip 兜底
pip install -e ~/workspace/model_api_connection
```

**2. 配置 API key**

推荐方式：通过 `llm-sync-keys` 从 1Password 同步到 `~/.config/llm/keys.env`（详见下方 CLI 工具章节）：

```bash
uv run llm-sync-keys          # 需安装并登录 op CLI
```

`model_connector` 在 import 时会自动加载 `~/.config/llm/keys.env`，shell 中已导出的同名变量优先级更高，不会被覆盖。

或直接导出环境变量：

```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GEMINI_API_KEY=AIza...
export SILICONFLOW_API_KEY=sf-...
export POE_API_KEY=...
export MEAI_API_KEY=...
```

---

## 公共 API

模块导出 4 个公共符号（`__all__`）：

### 模块级函数

| 函数签名 | 返回值 | 说明 |
|----------|--------|------|
| `chat(messages, *, provider, model=None, stream=False, **kwargs)` | `str \| Iterator[str]` | 模块级快捷调用，无需实例化 |
| `get_connector(**kwargs)` | `LLMConnector` | 获取/创建单例连接器 |
| `strip_think_stream(chunks: Iterator[str])` | `Iterator[str]` | 过滤流式输出中的 `<think>...</think>` 推理块，只保留最终回答 |

### LLMConnector 类

**构造函数：** `LLMConnector(config_path=None, api_keys=None)`

| 方法签名 | 返回值 | 说明 |
|----------|--------|------|
| `chat(messages, *, provider, model=None, stream=False, **kwargs)` | `str \| Iterator[str]` | 发送聊天请求 |
| `list_providers()` | `list[str]` | 所有已配置的 provider 名称 |
| `list_models(provider)` | `list[str]` | 指定 provider 的所有模型别名 |
| `default_model(provider)` | `str` | 指定 provider 的默认模型 |

**`**kwargs` 支持 litellm 的所有参数**，包括 `temperature`、`max_tokens`、`tools`、`tool_choice` 等。

---

## 使用示例

### 基本调用

```python
from model_connector import LLMConnector

llm = LLMConnector()

# 单条消息
response = llm.chat("你好", provider="siliconflow", model="deepseek-v3")

# 使用 provider 默认模型
response = llm.chat("Hi", provider="openai")

# Poe
response = llm.chat("Hi", provider="poe", model="Claude-Sonnet-4.5")
```

### 流式输出

```python
for chunk in llm.chat("解释量子纠缠", provider="anthropic", model="sonnet-4.6", stream=True):
    print(chunk, end="", flush=True)
```

### 多轮对话

```python
messages = [
    {"role": "system", "content": "你是简洁的助手。"},
    {"role": "user", "content": "我叫小明"},
    {"role": "assistant", "content": "你好，小明！"},
    {"role": "user", "content": "我叫什么名字？"},
]
response = llm.chat(messages, provider="openai", model="gpt-4o")
```

### Function Calling / Tool Use

```python
tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "获取指定城市的天气信息",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string", "description": "城市名称"}},
                "required": ["city"],
            },
        },
    }
]

response = llm.chat("北京天气怎么样？", provider="openai", tools=tools)
```

litellm 会自动将 OpenAI 格式的 tools 定义转换为各 provider 的原生格式。

### 模块级快捷调用（无需实例化）

```python
from model_connector import chat

response = chat("Hi", provider="gemini", model="gemini-2.5-flash")
```

### 传递额外 API 参数

```python
response = llm.chat("...", provider="openai", model="gpt-4o", temperature=0.2, max_tokens=512)
```

### 推理模型 — 过滤 `<think>` 块

DeepSeek-R1、Kimi-K2.5 等推理模型会在最终回答前输出思考过程。用 `strip_think_stream()` 只获取最终回答：

```python
from model_connector import chat, strip_think_stream

stream = chat("解释递归", provider="siliconflow", model="deepseek-r1", stream=True)
for chunk in strip_think_stream(stream):
    print(chunk, end="", flush=True)
# 输出：递归是指函数调用自身...（无推理过程）
```

---

## 模型名称

`models_config.json` 中的 key 是简短易记的别名，value 是 litellm 格式的模型 ID（`provider/model`）。

| Provider | 别名（你输入的） | litellm ID（实际发送的） |
|----------|-----------------|------------------------|
| openai | `gpt-4o` | `openai/gpt-4o` |
| openai | `o4-mini` | `openai/o4-mini` |
| anthropic | `sonnet-4.6` | `anthropic/claude-sonnet-4-6` |
| anthropic | `haiku-4.5` | `anthropic/claude-haiku-4-5-20251001` |
| gemini | `gemini-2.5-flash` | `gemini/gemini-2.5-flash` |
| siliconflow | `deepseek-v3` | `siliconflow/deepseek-ai/DeepSeek-V3` |
| poe | `Claude-Sonnet-4.5` | `poe/Claude-Sonnet-4.5` |
| meai | `claude-sonnet-4-6` | `openai/claude-sonnet-4-6` |
| meai | `glm-5.1` | `openai/glm-5.1` |

也可以直接传未在 config 中注册的模型 ID，会原样转发：

```python
chat("Hi", provider="openai", model="gpt-5")  # 未注册的名称，直接透传
```

---

## 添加新 provider / 中转商

编辑 `models_config.json`，加一条 provider 即可，无需改代码：

```json
"my_relay": {
    "api_key_env": "MY_RELAY_API_KEY",
    "base_url": "https://relay.example.com/v1",
    "default_model": "gpt-4o",
    "models": {
        "gpt-4o": "openai/gpt-4o"
    }
}
```

对于 OpenAI 兼容的中转商，只需配 `base_url` 即可。litellm 通过模型 ID 的 `provider/` 前缀自动识别协议。

---

## 更新模型

新模型发布时，编辑 `models_config.json`：

```json
"siliconflow": {
  "models": {
    "deepseek-v4": "siliconflow/deepseek-ai/DeepSeek-V4"
  }
}
```

用 `fetch_models.py` 从 API 查询最新可用模型。

---

## 视频理解

### video_connector.py

统一视频理解接口，支持 Gemini 和 Qwen。

```python
from video_connector import chat_with_video

# 基本用法（默认 prompt：完整总结视频内容）
result = chat_with_video("video.mp4", provider="gemini")

# 自定义 prompt
result = chat_with_video(
    "video.mp4",
    prompt="列出视频中出现的所有产品名称",
    provider="gemini",
    model="gemini-2.5-flash",
)

# 使用 Qwen
result = chat_with_video("video.mp4", prompt="描述视频内容", provider="qwen")
```

**处理策略：**

| 视频大小 | Provider | 传输方式 |
|---------|---------|---------|
| < 20 MB | 任意 | base64 内联 |
| ≥ 20 MB | gemini | Gemini File API（自动上传） |
| ≥ 20 MB | qwen | base64 内联（Qwen 支持最大 2 GB） |

环境变量：`GEMINI_API_KEY`（大视频走 File API 时必须设置）

---

### gemini_uploader.py

将本地视频上传到 Gemini File API，轮询直到处理完成，返回文件 URI。`video_connector` 内部自动调用，也可单独使用。

```python
from gemini_uploader import upload_video

uri = upload_video("video.mp4", api_key="AIza...")
# 返回: "https://generativelanguage.googleapis.com/v1beta/files/..."
```

---

## LLM 用量监控

`usage_log.py` 通过 litellm callback 自动记录每次调用，写入 JSONL 文件。

### 零侵入接入

消费方项目只需安装并导入，无需任何额外配置：

```bash
pip install -e /path/to/model_api_connection
```

```python
from model_connector import chat  # 导入即自动注册，所有调用自动记录
```

也可显式调用（幂等）：

```python
import usage_log
usage_log.register()  # 幂等，可重复调用
```

调用后，所有经过 litellm 的请求（成功或失败）都会追加写入：

```
~/Library/Mobile Documents/iCloud~md~obsidian/Documents/llm-usage/<hostname>.jsonl
```

可通过 `LLM_USAGE_DIR` 环境变量覆盖默认目录。

### iCloud 同步与多端聚合

日志目录默认位于 iCloud 同步路径，文件自动跨设备同步。每台机器写入自己的 `<hostname>.jsonl`，在任意一台机器上执行 `llm-stats` 即可看到所有已同步设备的记录。

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_USAGE_DIR` | `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/llm-usage` | JSONL 输出目录 |
| `LLM_CALLER` | `sys.argv[0]` | 调用方标识（覆盖自动检测） |
| `LLM_LOG_PAYLOAD` | 未设置 | 设为 `1` 时记录完整 prompt 和 completion |

### cron / launchd 署名（LLM_CALLER）

无人值守任务无法自动识别调用方，建议显式设置 `LLM_CALLER`：

```bash
LLM_CALLER=daily-summary python ~/scripts/daily.py
```

事后可按 caller 聚合查询：

```bash
llm-stats --since 7d --by caller
```

### 临时记录 prompt/completion（LLM_LOG_PAYLOAD）

调试时可临时开启完整内容记录：

```bash
LLM_LOG_PAYLOAD=1 python ~/scripts/repro.py
llm-stats --tail 1 --raw | jq '.prompt, .completion'
```

### 日志字段

每行 JSON 包含：`ts`、`host`、`provider`、`model`、`caller_script`、`input_tokens`、`output_tokens`、`cost_usd`、`latency_ms`、`status`（`success`/`error`）、`error`、`request_id`、`stream`。

### 异常隔离

写日志失败时只向 stderr 打印警告，不影响主调用链。

### llm-stats CLI

`llm-stats` 为注册的命令行工具，安装后可直接使用：

```bash
uv run llm-stats                                            # 最近 24h，按 provider 聚合
uv run llm-stats --since 1h --by caller                     # 最近 1h，按 caller 聚合
uv run llm-stats --since 7d --by host                       # 最近一周，按机器聚合
uv run llm-stats --filter provider=siliconflow --since 36h  # 排查异常 provider
uv run llm-stats --filter caller~runaway --raw              # 看具体调用
uv run llm-stats --tail 50                                  # 最近 50 条原始记录
uv run llm-stats --paths                                    # 打印日志目录与各文件状态
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--since` | `24h` | 时间窗口：`1h` / `24h` / `7d` / `30m` / ISO 8601 |
| `--by` | `provider` | group by 键，逗号分隔：`provider` / `model` / `caller` / `host` |
| `--filter` | 无 | `key=val` 精确匹配 / `key~val` 子串，可多次指定 |
| `--raw` | 关 | 输出原始 JSONL，便于管道给 `jq` |
| `--tail` | 0 | 只看最近 N 条原始记录（按 ts 排序） |
| `--paths` | 关 | 打印 `USAGE_DIR` 路径和各 `.jsonl` 文件行数/大小 |

### 查询 API（`cli/llm_stats.py`）

`_parse_since(value, now=None)` — 解析时间窗口，支持相对格式（`1h` / `24h` / `7d` / `30m`）或 ISO 8601：

```python
from cli import llm_stats
import datetime as dt

cutoff = llm_stats._parse_since("24h")           # 过去 24 小时
cutoff = llm_stats._parse_since("2026-04-19T00:00:00Z")  # 绝对时间
```

`_parse_filter(specs)` — 解析过滤条件列表，支持精确匹配（`=`）和子串匹配（`~`）：

```python
filters = llm_stats._parse_filter(["provider=openai", "caller~runaway.py"])
# -> [("provider", "=", "openai"), ("caller", "~", "runaway.py")]
```

`_apply_since(rows, cutoff)` / `_apply_filters(rows, filters)` — 流式过滤（生成器）：

```python
rows = llm_stats._iter_records()
rows = llm_stats._apply_since(rows, cutoff)
rows = llm_stats._apply_filters(rows, filters)
```

`_aggregate(rows, by)` — 按多键 group by，汇总 calls / input_tokens / output_tokens / cost_usd（cost 全为 null 则聚合结果也为 null）：

```python
result = llm_stats._aggregate(rows, by=["provider", "host"])
# -> [{"provider": "openai", "host": "mac1", "calls": 5, "input_tokens": 1200, ...}, ...]
```

### 消费方 CLAUDE.md 推荐模板

在消费方项目的 `CLAUDE.md` 中加入以下片段，让 AI 助手知道如何处理 LLM 调用记录：

```
## LLM 调用
用 `from model_connector import chat`。所有调用自动记录到本机 iCloud 同步的
`llm-usage/`，可在任意机器跑 `llm-stats` 查询。
cron / 长期脚本请设 `LLM_CALLER=<task-name>` 便于事后追溯。
```

---

## CLI 工具

### 同步 API Key（从 1Password）

`key_sync.py` 从 1Password 读取 API key，写入 `~/.config/llm/keys.env`（权限 600）。

**前置条件：** 安装并登录 `op` CLI（`brew install 1password-cli`），在 1Password 应用 -> Settings -> Developer -> 开启 "Integrate with 1Password CLI"。密钥真相源是 1Password vault `llmkeys`（每个 provider 一条 API Credential 条目）。

在 `models_config.json` 的 provider 中添加 `op_reference`（如 `op://llmkeys/OpenAI/credential`）字段后即可使用：

```bash
uv run llm-sync-keys                        # 同步所有配置了 op_reference 的 provider
uv run llm-sync-keys --provider openai      # 只同步 openai，保留其他 key 不变
uv run llm-sync-keys --dry-run              # 预览将要同步的内容，不实际执行
```

**同步语义：**

- **完整同步**（无 `--provider`）：**覆盖整个 keys.env 文件**。1Password 中配置的 key 是唯一的可信源（SSoT）；未在 1Password 中配置的 key（包括旧 key 和自定义 key）会被删除。
- **单 provider 同步**（`--provider openai`）：**只更新指定 provider 对应的 key**，保留其他 key 不变。适合增量更新和保护本地自定义 key。

### 测试 API 连通性

```bash
python test_models.py                              # 测试所有 provider 的默认模型
python test_models.py --provider siliconflow --all  # 测试某个 provider 的所有模型
python test_models.py --provider anthropic --model sonnet-4.6  # 测试特定模型
python test_models.py --all                         # 全量测试
```

### 拉取在线模型列表

显示：**Model ID · Age · $/1M (in/out) · Ctx · Flags · Description**

```bash
python fetch_models.py                    # 所有 provider，最近 6 个月
python fetch_models.py --all              # 全部模型，不限时间
python fetch_models.py --current          # 只显示 models_config.json 中已配置的
python fetch_models.py --provider openai  # 单个 provider
python fetch_models.py --months 3         # 自定义时间窗口
```

### 运行单元测试

```bash
pytest tests/
```

---

## 在其他项目中使用

### 推荐：uv editable install

```bash
uv add --editable ~/workspace/model_api_connection
# 或 pip 兜底
pip install -e ~/workspace/model_api_connection
```

然后直接 import：

```python
from model_connector import chat, LLMConnector, strip_think_stream
```

### 备选：sys.path（免安装）

```python
import sys
sys.path.insert(0, "/path/to/model_api_connection")
from model_connector import chat
```

### 给 AI Agent 的调用指南

在其他项目的 `CLAUDE.md` 中加入以下内容，AI 即可直接调用：

```markdown
## LLM API 调用

本项目通过 model_api_connection 连接大模型（已 `uv add --editable` 安装）。

\```python
from model_connector import chat, LLMConnector, strip_think_stream

# 一句话调用
response = chat("prompt", provider="openai")  # 可选: anthropic / gemini / siliconflow / poe

# 流式输出
for chunk in chat("prompt", provider="anthropic", stream=True):
    print(chunk, end="")

# Function calling / Tool use
response = chat("prompt", provider="openai", tools=[...])

# 推理模型去除思考过程
for chunk in strip_think_stream(chat("prompt", provider="siliconflow", model="deepseek-r1", stream=True)):
    print(chunk, end="")

# 查看可用模型
LLMConnector().list_models("openai")
\```

可用 provider: openai, anthropic, gemini, siliconflow, poe, meai
```
