# Model API Connection — 1Password 密钥同步改造

**日期**：2026-04-19
**状态**：已 approve（brainstorm 阶段）
**负责人**：xuche

---

## 1. 问题

Model API Connection（`~/workspace/model_api_connection`）定位是所有本地项目的统一 LLM 网关，但当前实现有三个未解决的问题：

1. **密钥不具备可移植性**。`python-dotenv` 从调用方的 CWD 加载 `.env`，不是从本仓库。其他项目 `pip install -e` 本 connector 后，除非每个项目各复制一份 `.env`、或者用户恰好在本仓库目录下运行，否则拿不到密钥。
2. **不支持无人值守（cron / launchd）场景**。用户计划在 Mac Mini 上跑定时 LLM 任务，当前流程依赖的 shell 环境在 cron 里并不存在。
3. **密钥散落、缺可读真相源**。人肉查看/修改密钥没有统一入口——轮换一个 key 要在 N 台机器改 N 个文件，没有 UI 可以回答"我当前的 OpenAI key 是哪个？"。

额外背景：用户手头有 3+ 台个人 Mac、1 台工作用 Mac Air，以及即将上线的 Mac Mini（作为家用常驻服务器），所有机器共用同一套密钥。用户刚订阅了 1Password。

## 2. 目标

- **密钥有单一真相源**，且人肉可浏览（1Password UI）。
- **Python 项目零摩擦调用**：`from model_connector import chat` 直接能用，和 CWD 无关。
- **兼容 cron / launchd**：定时任务不需要任何交互解锁。
- **跨机器**：新 Mac 上线 10 分钟内搞定。
- **默认安全**：密钥绝不进 git；本地文件统一 `chmod 600`。

## 3. 不做的事（Non-Goals）

- 做可插拔 key backend（env / Keychain / 1P / Vault 一锅烩）—— YAGNI。
- 自建 1Password Connect 服务——个人场景过度设计。
- 用 1Password Service Account（需要 1P Business 订阅）——本地缓存方案能达到同样效果，省订阅费。
- 自动轮换调度——手动足够，轮换频率本来就低。
- 给本地缓存再加一层加密（age / gpg 套在 `keys.env` 外）—— FileVault + `chmod 600` 已足够；再套加密还得存私钥，增加复杂度而安全收益几乎为零。
- 把个人档案 / 用户上下文注入到 prompt——独立议题，通过 `~/.claude/CLAUDE.md` 的 `@` 导入机制单独处理。
- Shell CLI（`llm chat ...`）—— 等真有非 Python 消费方时再加。

## 4. 架构

```
+-----------------------------------------+
|  1Password Vault "llmkeys" (SSoT)      |
|  - OpenAI                               |
|  - Anthropic                            |
|  - Gemini                               |
|  - SiliconFlow                          |
|  - Poe                                  |
+-----------------------------------------+
                 |
                 | op read（按需触发：首次 / 轮换）
                 v
+-----------------------------------------+
|  ~/.config/llm/keys.env (chmod 600)     |
|  OPENAI_API_KEY=sk-...                  |
|  ANTHROPIC_API_KEY=sk-ant-...           |
|  ...                                    |
+-----------------------------------------+
                 |
                 | load_dotenv（固定路径，与 CWD 无关）
                 v
+-----------------------------------------+
|  消费侧                                  |
|  - from model_connector import chat     |
|  - cron 脚本                             |
+-----------------------------------------+
```

### 核心设计原则

- **1Password 是人肉真相源**：查看、编辑、轮换全部在 1P UI 里完成。
- **`~/.config/llm/keys.env` 是程序真相源**：connector 只读这个文件（可被显式参数覆盖），调用时从不碰 1P。
- **`llm-sync-keys` 是桥**：一个小命令，调 `op` 读 1P、写本地缓存。只在首次搭建、密钥轮换、新机器接入时跑，其他时候用不到。
- **日常调用从不访问 1P**：cron、交互式 Python、测试都只读本地缓存。

## 5. 组件

### 5.1 1Password Vault 结构

用户已手动创建：

- Vault 名：`llmkeys`
- 条目（每条含一个 `credential` 字段，内容是 API key）：
  - `OpenAI`
  - `Anthropic`
  - `Gemini`
  - `SiliconFlow`
  - `Poe`

条目类型用 **API Credential**（1P 内置类型）。密钥通过 `op://llmkeys/<item>/credential` 引用。

### 5.2 新增文件

| 文件 | 作用 | 预估行数 |
|------|------|---------|
| `key_sync.py` | `llm-sync-keys` 命令 —— 读 1P，写 `keys.env` | ~80 |
| `paths.py` | 路径常量：`KEYS_ENV_PATH = Path.home() / ".config/llm/keys.env"` | ~20 |
| `tests/test_key_sync.py` | sync 的单元测试（mock `op`） | ~100 |

### 5.3 修改文件

**`model_connector.py`**
- 模块导入时自动加载 `~/.config/llm/keys.env`（可被显式参数覆盖）。
- 修复 singleton bug：`get_connector(**kwargs)` 当前只要传了 kwargs 就重建单例（原因是 `_default_connector is None or kwargs` 的逻辑错）。新行为：按 kwargs 哈希缓存，或只在 kwargs 变化时重建。
- 新增 `chat()` 的 `raw: bool = False` 参数 —— 为 True 时返回完整 litellm response 对象，而不是只返回 `.choices[0].message.content`。用于 tool-use 场景（当前代码丢掉了 `tool_calls`）。
- 改进 keys.env 缺失时的错误信息：提示去跑 `llm-sync-keys`。
- 公共 API（`__all__`）保持不变，现有调用方无需改动。

**`models_config.json`**
- 每个 provider 加 `op_reference` 字段：
  ```json
  "openai": {
    "api_key_env": "OPENAI_API_KEY",
    "op_reference": "op://llmkeys/OpenAI/credential",
    "default_model": "gpt-4o",
    "models": { ... }
  }
  ```
- `key_sync.py` 读这个字段决定从 1P 拉哪条。
- provider 如果没配 `op_reference`，`llm-sync-keys` 跳过它（允许混源配置）。

**`pyproject.toml`**
- 增加 console script：
  ```toml
  [project.scripts]
  llm-sync-keys = "key_sync:main"
  ```
- 保留现有 `py-modules` 和 optional-deps 配置。

**`README.md`**
- 把 `.env` 配置章节替换成 1Password + `llm-sync-keys` 的新流程。
- 安装说明从 `pip install -e .` 改成 `uv add --editable <path>`（保留一行 pip 兜底说明）。
- 新增"新 Mac 接入"小节，给出 5 分钟 checklist。

**`.env.example`** —— 删除。被 1P `llmkeys` vault + `llm-sync-keys --help` 替代。

### 5.4 `llm-sync-keys` 行为

```
$ llm-sync-keys
[1Password] Authenticating...   (首次/session 过期会弹 Touch ID)
- OpenAI        op://llmkeys/OpenAI/credential         -> OPENAI_API_KEY
- Anthropic     op://llmkeys/Anthropic/credential      -> ANTHROPIC_API_KEY
- Gemini        op://llmkeys/Gemini/credential         -> GEMINI_API_KEY
- SiliconFlow   op://llmkeys/SiliconFlow/credential    -> SILICONFLOW_API_KEY
- Poe           op://llmkeys/Poe/credential            -> POE_API_KEY

Wrote 5 keys to ~/.config/llm/keys.env (chmod 600).

$ llm-sync-keys --dry-run
（打印将要拉的条目，不调 op，不写文件）

$ llm-sync-keys --provider openai
（只拉一个 provider，用于单条轮换）
```

实现要点：
- 用 subprocess 调 `op`：`subprocess.run(["op", "read", ref], capture_output=True, text=True)`。
- `op` 未安装：提示 `brew install 1password-cli`，exit 1。
- `op` 未认证（错误文本含 "not signed in"）：提示去 1P App 勾 "Integrate with 1Password CLI"，exit 1。
- 单条失败：打印哪条失败，继续跑剩下的；整体有任何失败就以非零状态退出。
- 先写临时文件再原子 rename，保证失败时不会留下半截文件。
- 最终文件统一 `chmod 600`。
- `~/.config/llm/` 不存在就创建，权限 `0700`。

## 6. 数据流

**场景 A：任意项目里跑 Python**
```
$ cd ~/workspace/some-other-project
$ python -c "from model_connector import chat; print(chat('hi', provider='openai'))"
-> model_connector import 时执行 load_dotenv("~/.config/llm/keys.env")
-> chat() 从环境变量里取 api_key（此时已被注入）、调 litellm、返回
```

**场景 B：cron / launchd**
```
(launchd) 跑 /usr/bin/python3 ~/scripts/daily-summarize.py
-> 脚本 import model_connector
-> 同样 load_dotenv、同样路径，无需人工交互
-> 跑完退出
```

**场景 C：密钥轮换**
```
1. 在 provider 的后台（比如 OpenAI Settings -> API keys）轮换 key
2. 把新 key 粘贴到 1P 条目 "llmkeys/OpenAI"
3. 在每台活跃 Mac 上：llm-sync-keys --provider openai
4. 下一次调用自动用新 key
```

**场景 D：新 Mac 接入**
```
1. 装软件：brew install 1password 1password-cli uv
2. 登录 1P App；打开 Settings -> Developer -> 勾 "Integrate with 1Password CLI"
3. 有需要就 clone workspace，或在已有路径上 `uv add --editable`
4. 跑：llm-sync-keys         （Touch ID，拉全部条目）
5. 验证：python -c "from model_connector import chat; print(chat('ping', provider='openai'))"
```

## 7. 错误处理

| 场景 | 行为 |
|------|------|
| `~/.config/llm/keys.env` 不存在，connector 初始化时 | 不立即抛异常；让 `chat()` 走现有的"API key not found"路径，但信息增加一句："... or run `llm-sync-keys` to populate cache." |
| `keys.env` 存在但某个 key 缺失 | 同当前：明确指出缺少哪个环境变量。 |
| `op` CLI 未装 | `llm-sync-keys` 提示 `brew install 1password-cli`，exit 1。 |
| `op` CLI 未认证 | `llm-sync-keys` 提示启用 CLI integration 的步骤，exit 1。 |
| 单条 `op read` 失败 | 记录、跳过、继续其他条目；最终以非零状态退出。 |
| litellm API 调用失败 | 原样透传异常，不吞。 |

## 8. 测试

- **单元测试（`tests/test_key_sync.py`）**：mock `subprocess.run` 模拟 `op` 的各种行为——成功、命令不存在、未认证、部分失败。校验输出文件权限是 `0600` 且用了原子 rename。
- **现有 `tests/` 保持通过**：集成测试只要求相应的 `*_API_KEY` 环境变量存在；它们不关心 value 来自 `keys.env` 还是 shell env。
- **在一台 Mac 上手动验收**：
  1. 在 1P vault 里建好占位测试 key
  2. 跑 `llm-sync-keys`
  3. 确认 `~/.config/llm/keys.env` 存在、权限 `0600`、包含预期变量
  4. 在一个无关 CWD 下跑 `python -c "from model_connector import chat; print(chat('ping', provider='openai'))"`
  5. 在 1P 里改一个 key，跑 `llm-sync-keys --provider openai`，确认已刷新

## 9. 多项目接入协议

消费方项目**只做两件事**：

**一次性安装：**
```
uv add --editable ~/workspace/model_api_connection
```

**使用：**
```python
from model_connector import chat
response = chat("你好", provider="openai")
```

不配 `.env`、不改环境变量、不改 PATH、不复制密钥。

每个消费项目的 `CLAUDE.md` 里加一段"LLM 调用"小节（copy-paste 模板放在 `model_api_connection/README.md`），任何在该项目工作的 Claude / agent 都能立刻知道 import 姿势。

## 10. 迁移计划

顺序有讲究——保证迁移过程中消费方项目不被打断。

1. 用户在 1P `llmkeys` vault 里填好 5 条现有 key（本项目之外的操作，已完成）。
2. 实现 `paths.py`、`key_sync.py`、`tests/test_key_sync.py`，更新 `pyproject.toml`。提交。
3. 在 `models_config.json` 加 `op_reference`。提交。
4. 更新 `model_connector.py`：固定路径自动加载、修 singleton bug、加 `raw=True`、改进错误信息。提交。
5. 在本 Mac 跑 `llm-sync-keys`。确认缓存工作正常后，删仓库里旧的 `.env`。
6. 更新 `README.md`，删除 `.env.example`。提交。
7. 在其他 Mac 上依次按场景 D 的 bootstrap 流程操作。
8. 每个消费方项目：`uv add --editable ...`，删掉本地 `.env` 的重复配置，验证。

## 11. 验收标准

- 在本 Mac 任意目录下跑 `python -c "from model_connector import chat; print(chat('ping', provider='openai'))"`，无需任何环境准备即可成功。
- `launchctl` 能跑一个调 `chat(...)` 的 Python 脚本，无需人工交互。
- 删掉 `~/.config/llm/keys.env` 会让调用失败；跑 `llm-sync-keys` 能恢复。
- `~/.config/llm/keys.env` sync 之后权限是 `0600`。
- model_api_connection 的 git 历史、工作树、任何提交文件里都没有 API 密钥。
- `tests/` 全部通过。

## 12. 待定问题

- 无阻塞项。回头可能再看：
  - `llm-sync-keys` 要不要支持 `--watch` 定时重跑？（大概率不用，轮换很少见。）
  - 要不要给 `keys.env` 加一行"上次轮换时间"元数据？（锦上添花，暂缓。）
  - 消费方项目要不要锁 model_api_connection 的某个 commit，还是跟 `main`？（默认跟 `main` 的 editable install，个人场景灵活为主。）

## 13. 范围外（另行处理）

- 个人档案注入（设备清单、身份、工作上下文）——通过 Claude Code 的 `~/.claude/CLAUDE.md` `@` 导入，独立议题。
- Claude Code 订阅 token 在定时任务里复用的问题——CLAUDE.md 里已标记，每个任务单独评估。
