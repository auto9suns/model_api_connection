# LLM API Connector

轻量级、配置驱动的多模型统一连接器，底层基于 [litellm](https://github.com/BerriAI/litellm)。一次 import，统一调用 OpenAI / Anthropic / Gemini / SiliconFlow / Poe 及任何 OpenAI 兼容 API。

---

## 快速接入（其他项目）

```bash
# 推荐：安装为可编辑包
pip install -e /path/to/model_api_connection
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
| `gemini_uploader.py` | 上传视频到 Gemini File API，等待处理完成，返回 URI |
| `video_connector.py` | 统一视频理解接口，支持 Gemini / Qwen |
| `models_config.json` | 模型注册表（增删模型改这里） |
| `test_models.py` | CLI 工具：验证 API key 和模型连通性 |
| `fetch_models.py` | CLI 工具：从 API 拉取最新模型列表 |
| `_fetch_helpers.py` | fetch_models.py 的内部辅助模块 |
| `usage_log.py` | LLM 调用日志底层：路径解析 + JSONL writer |
| `tests/` | 单元测试（`pytest tests/`） |
| `.env.example` | API key 模板 |

---

## 安装

**1. 安装依赖**

```bash
pip install -r requirements.txt
# 或安装为包：
pip install -e .
```

**2. 配置 API key**

```bash
cp .env.example .env
# 编辑 .env 填入你的 key
```

或直接导出环境变量：

```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
export GEMINI_API_KEY=AIza...
export SILICONFLOW_API_KEY=sf-...
export POE_API_KEY=...
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

## CLI 工具

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

### 推荐：pip install

```bash
pip install -e /path/to/model_api_connection
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

本项目通过 model_api_connection 连接大模型（已 pip install -e 安装）。

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

可用 provider: openai, anthropic, gemini, siliconflow, poe
```
