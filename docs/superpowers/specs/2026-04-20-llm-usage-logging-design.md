# Model API Connection — LLM 调用记录与监控

**日期**：2026-04-20
**状态**：已 approve（brainstorm 阶段）
**负责人**：xuche

---

## 1. 问题

`model_api_connection` 当前对外只暴露 `chat()`，跑完不留痕迹。具体痛点：

1. **不知道谁调了 LLM**。SiliconFlow 在 2026-04-19 凌晨到 2026-04-20 中午区间烧掉约 50 元，但本人不记得跑了什么任务。当下没有任何方式回答"过去 24 小时谁调用了 LLM、调了什么模型、调了多少次"。
2. **多项目调用方无统一记录**。本仓库被多个其他项目 `pip install -e` 后调用（`from model_connector import chat`），消费方各自不写日志，事故无法溯源。
3. **多端调用分散**。本人 4 台 Mac 都会跑 `chat()`：随身 MBP、公司 MBA、公司 Mac mini、个人 Mac mini。事故发生时不知道是哪台机器在跑，也没办法在一台机器上查全集。

## 2. 目标

- **每次 `chat()` 自动留底**：consumer 项目零改动，import 即记录。
- **能回答"谁/何时/什么"**：调用方脚本路径、cwd、机器名、provider、model、token、cost、状态。
- **跨 4 台 Mac 可聚合查询**：在任意一台机器上能看到全部 4 台的调用历史。
- **轻量**：无 daemon，无中心服务器，无外部依赖（除已有 iCloud + litellm）。
- **失败不影响业务**：日志写挂了不能让 `chat()` 抛异常。
- **CLI 即可查询**：不做 dashboard，不做实时告警（v1 范围）。

## 3. 不做的事（Non-Goals）

- **实时告警** —— v2 再加（launchd 日报 / 阈值通知）。当前只保证有日志，事后能查。
- **中心化日志服务** —— 不自建 server。Mac Mini 装好系统并跑稳了之后再考虑切 Tailscale 中心方案。
- **在线 dashboard** —— `llm-stats` CLI + Datasette（按需）已足够。
- **自动 prompt 脱敏** —— payload 默认不存；需要时显式开 `LLM_LOG_PAYLOAD=1`，由用户负责保密。
- **跨账号聚合** —— 个人单用户场景，不考虑多用户合并。
- **写日志走第三方服务**（Helicone / Langfuse / LiteLLM Proxy）—— 个人场景不引入第三方。
- **替换 litellm 自身的 callback 机制** —— 用 `litellm.success_callback` / `failure_callback` 直接挂钩。
- **追加 chat() 的 `tags=` 参数让用户打标签** —— YAGNI，等真有需求再加。

## 4. 架构

```
+-----------------------------------------------+
|  consumer 项目（任意 cwd、任意机器）             |
|  from model_connector import chat              |
|  chat("hi", provider="openai")                 |
+-----------------------------------------------+
                      |
                      | (1) model_connector import 时
                      |     usage_log.register() 把 callback
                      |     挂进 litellm.success/failure_callback
                      v
+-----------------------------------------------+
|  litellm.completion(...)                       |
|  调用结束后触发 callback                         |
+-----------------------------------------------+
                      |
                      | (2) callback 收集 metadata
                      |     append 一行 JSON
                      v
+-----------------------------------------------+
|  ~/Library/Mobile Documents/                   |
|    iCloud~md~obsidian/Documents/llm-usage/     |
|    Xus-MacBook-Pro.jsonl   ┐                   |
|    work-mba.jsonl          │ iCloud 自动同步    |
|    personal-mini.jsonl     │ 到所有机器          |
|    work-mini.jsonl         ┘                   |
+-----------------------------------------------+
                      |
                      | (3) 任意机器跑 llm-stats
                      v
+-----------------------------------------------+
|  llm-stats CLI                                 |
|  - 读所有 *.jsonl                              |
|  - 加载到内存 sqlite                            |
|  - 按 since / by / filter 聚合输出              |
+-----------------------------------------------+
```

### 核心设计原则

- **零侵入**：consumer 只 `import chat`，callback 自动注册。无需手动初始化、无需传 logger。
- **每机一份文件**：`<hostname>.jsonl`，每台机器只写自己那个文件，append-only，iCloud 同步无冲突风险。
- **JSONL 不用 SQLite**：SQLite 在 iCloud 同步下有损坏风险（特别是 WAL 模式 + 多端并发），JSONL 每行原子追加，安全。
- **callback 异常隔离**：日志逻辑 try/except 包裹，写挂、磁盘满、iCloud 离线都不影响主调用。
- **metadata-only 默认**：不存 prompt/completion，避免隐私泄漏和文件膨胀；调试时可临时开 `LLM_LOG_PAYLOAD=1`。
- **查询用内存 SQLite**：不维护持久 DB，每次 `llm-stats` 启动时把 JSONL 加载到 `:memory:`，跑完即弃。

## 5. 组件

### 5.1 新增文件

| 文件 | 作用 | 预估行数 |
|------|------|---------|
| `usage_log.py` | callback 注册 + JSONL writer + 路径管理 + caller 识别 | ~100 |
| `cli/__init__.py` | 空，标识 cli 子包 | 0 |
| `cli/llm_stats.py` | `llm-stats` CLI：聚合、过滤、表格输出 | ~140 |
| `tests/test_usage_log.py` | callback / writer / caller 识别 / 异常隔离 单测 | ~120 |
| `tests/test_llm_stats.py` | CLI 聚合 / 过滤 / 损坏行容错 单测 | ~80 |

### 5.2 修改文件

**`model_connector.py`**
- 在 module 顶部 `import` 段后追加 `from usage_log import register as _register_usage_log; _register_usage_log()`。
- `_register_usage_log()` 内部幂等：检查 `_log_success` 是否已经在 `litellm.success_callback` 列表里，避免多次 import 时重复挂钩。
- 公共 API（`__all__`）保持不变。
- 与 1P 密钥管理、singleton bug、`raw=True` 等其他 PR 修改完全正交，仅追加 2 行。

**`pyproject.toml`**
- 新增 console script：
  ```toml
  [project.scripts]
  llm-stats = "cli.llm_stats:main"
  ```
- `[tool.setuptools]` 的 `py-modules` 追加 `usage_log`，并新增 `packages = ["cli"]`（与现有 `py-modules` 共存，setuptools 支持两者并用）。

**`README.md`**
- 新增"LLM 用量监控"章节，介绍：
  - 日志默认路径
  - `llm-stats` 用法
  - 如何用 `LLM_CALLER` 给 cron/launchd 任务命名
  - 如何临时开 payload 全文记录
  - iCloud 同步说明 + 多端聚合行为

### 5.3 数据 schema

每行 JSON，字段如下：

| 字段 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `ts` | str (ISO 8601 UTC) | 调用结束时间 | `"2026-04-20T03:14:22.157Z"` |
| `host` | str | `socket.gethostname()` | `"Xus-MacBook-Pro.local"` |
| `provider` | str | 配置文件中的 provider key | `"siliconflow"` |
| `model` | str | 解析后的 litellm model id | `"openai/Pro/moonshotai/Kimi-K2.5"` |
| `caller_script` | str | `LLM_CALLER` env 优先；否则 `sys.argv[0]`；否则 `"<repl>"` | `"$WORKSPACE_ROOT/foo/bar.py"` |
| `caller_cwd` | str | `os.getcwd()` | `"$WORKSPACE_ROOT/foo"` |
| `caller_pid` | int | `os.getpid()` | `54321` |
| `caller_ppid` | int | `os.getppid()`（追溯 cron / launchd 调用链） | `1` |
| `input_tokens` | int \| null | `response.usage.prompt_tokens`，拿不到时 null | `1234` |
| `output_tokens` | int \| null | `response.usage.completion_tokens` | `567` |
| `cost_usd` | float \| null | `litellm.completion_cost(response)`；不在 litellm 价格表的 provider（SiliconFlow / Poe）为 null | `0.0312` |
| `latency_ms` | int | 从 `chat()` 调用到 callback 触发的耗时 | `2150` |
| `status` | str | `"success"` 或 `"error"` | `"success"` |
| `error` | str \| null | 失败时填异常类型 + 消息（截断到 500 字符） | `null` |
| `request_id` | str | 每次调用生成的 uuid4，唯一标识一次 `chat()`，排查时方便从日志中精准定位 | `"a3b2..."` |
| `stream` | bool | 是否是流式调用 | `false` |
| `prompt` | str \| null | **仅当 `LLM_LOG_PAYLOAD=1`**：完整 messages 的 JSON 序列化 | `null` |
| `completion` | str \| null | **仅当 `LLM_LOG_PAYLOAD=1`**：完整响应文本 | `null` |

固定字段顺序写入，方便后续用 `jq` 等工具直读。

### 5.4 callback 注册机制

```python
# usage_log.py 关键骨架
import litellm

def register():
    if _log_success not in litellm.success_callback:
        litellm.success_callback.append(_log_success)
    if _log_failure not in litellm.failure_callback:
        litellm.failure_callback.append(_log_failure)

def _log_success(kwargs, response, start_time, end_time):
    try:
        _write_record(_build_record("success", kwargs, response, start_time, end_time))
    except Exception as e:
        _stderr_warn(f"usage_log success callback failed: {e}")

def _log_failure(kwargs, response, start_time, end_time):
    try:
        _write_record(_build_record("error", kwargs, response, start_time, end_time))
    except Exception as e:
        _stderr_warn(f"usage_log failure callback failed: {e}")
```

签名严格按 litellm 文档（`success_callback` 接收 `kwargs, completion_response, start_time, end_time`）。

### 5.5 caller 识别

```python
def _get_caller():
    return {
        "caller_script": os.environ.get("LLM_CALLER") or sys.argv[0] or "<repl>",
        "caller_cwd": os.getcwd(),
        "caller_pid": os.getpid(),
        "caller_ppid": os.getppid(),
    }
```

- `LLM_CALLER` 优先级最高，给 cron / launchd / 容器场景留显式署名口子。
- `sys.argv[0]` 在 IPython / Jupyter / `python -c` 下可能是空串或路径，fallback 到 `"<repl>"`。
- `caller_ppid` 让事后能追溯"是不是 cron 调起来的"——`ps -p <ppid>` 或日志关联。

### 5.6 路径管理

```python
DEFAULT_USAGE_DIR = (
    Path.home()
    / "Library/Mobile Documents/iCloud~md~obsidian/Documents/llm-usage"
)
USAGE_DIR = Path(os.environ.get("LLM_USAGE_DIR", DEFAULT_USAGE_DIR))
USAGE_FILE = USAGE_DIR / f"{socket.gethostname()}.jsonl"
```

- 复用 Obsidian 的 iCloud 容器，省创建新 iCloud 文件夹。
- 首次写入时 `mkdir(parents=True, exist_ok=True)`，目录权限 `0700`。
- 文件本身权限 `0600`（首次创建后 chmod）。
- `LLM_USAGE_DIR` 环境变量可覆盖，方便测试 / 不用 iCloud 的机器（如 CI、未来的 Tailscale 中心方案）。

### 5.7 写入策略

```python
def _write_record(record: dict) -> None:
    USAGE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    # POSIX 保证 < PIPE_BUF (通常 4096) 的 append 是原子的；
    # 单行 JSON 通常远小于 4096，不加锁。
    with open(USAGE_FILE, "a", encoding="utf-8") as f:
        f.write(line)
    if USAGE_FILE.stat().st_mode & 0o777 != 0o600:
        USAGE_FILE.chmod(0o600)
```

- 每次 append 一行，无 buffering 复杂度。
- 首次创建后 chmod 0600，之后 stat 检查避免每次 chmod 系统调用。
- 不引入 file lock：单机单文件，并发由文件系统保证（POSIX `O_APPEND` 短写原子）。

### 5.8 `llm-stats` CLI 行为

```
$ llm-stats
最近 24h（4 台 Mac 聚合）：
  调用:   2,143 次
  成本:   $4.21
  失败率: 1.2% (26 次)

按 provider:
  provider       calls    in_tok    out_tok   cost_usd
  siliconflow    1,800   1,200,000   850,000     null
  openai           200      45,000    32,000      $1.50
  anthropic        143      38,000    27,000      $0.61

按 caller (top 5):
  caller_script                        calls   cost_usd
  $WORKSPACE_ROOT/foo/bar.py    1,800     null
  $WORKSPACE_ROOT/baz/qux.py      200    $1.50
  ...

$ llm-stats --since 1h
$ llm-stats --since 7d --by host
$ llm-stats --by model
$ llm-stats --filter provider=siliconflow --since 24h
$ llm-stats --filter caller~bar.py --since 24h
$ llm-stats --raw --since 1h            # 输出 JSONL，便于 jq 后处理
$ llm-stats --tail 50                   # 最近 50 条原始记录
$ llm-stats --paths                     # 打印当前 USAGE_DIR + 各 host 文件状态
```

实现要点：
- 启动时 glob `USAGE_DIR/*.jsonl`，逐行读，加载到 `sqlite3.connect(":memory:")` 的临时表。
- `--since` 解析 `1h` / `24h` / `7d` / `30d` / ISO 时间。
- `--by` 支持 `provider` / `model` / `caller` / `host` / `caller,host` 等组合 group by。
- `--filter` 支持 `key=val`（精确）、`key~val`（substring）、可叠加。
- 表格输出自己实现简单对齐，避免引入新依赖。
- 损坏行（JSON parse 失败）跳过，stderr 提示文件 + 行号。

## 6. 数据流

**场景 A：任意项目里跑 `chat()`**
```
$ cd ~/workspace/some-project
$ python -c "from model_connector import chat; chat('hi', provider='openai')"
-> import 时 usage_log.register() 注册 callback
-> chat() 调 litellm.completion(...)
-> 成功后 litellm 触发 _log_success
-> _log_success append 一行 JSON 到 ~/.../llm-usage/<host>.jsonl
-> 失败/抛异常时触发 _log_failure，记录 status=error
```

**场景 B：cron / launchd 调度**
```
$ LLM_CALLER=daily-summary launchctl asuser ... python ~/scripts/daily.py
-> 同上，但 caller_script 字段 = "daily-summary"（明确署名）
-> 即使脚本在 /usr/bin/python3 子进程里，caller_ppid 能看出是 launchd
```

**场景 C：跨机器查询**
```
（在 MBP 上）
$ llm-stats --since 24h --by caller
-> 读 USAGE_DIR/*.jsonl
-> 自动看到 work-mba.jsonl / work-mini.jsonl 等其他机器同步过来的文件
-> 聚合输出全部 4 台机器的调用
```

iCloud 同步延迟通常秒级到分钟级；事故事后排查（小时级）完全够用。

**场景 D：紧急排查 SiliconFlow 异常**
```
$ llm-stats --since 36h --filter provider=siliconflow --by caller
caller_script                          calls    in_tok    out_tok
$WORKSPACE_ROOT/foo/runaway.py  18,432  9,200,000  6,300,000   ← 找到元凶
...

$ llm-stats --since 36h --filter caller~runaway --raw | jq '.ts' | head
（看具体调用时间分布）
```

**场景 E：调试某次怪输出**
```
$ LLM_LOG_PAYLOAD=1 python ~/scripts/repro.py
$ llm-stats --tail 1 --raw | jq '.prompt, .completion'
```

## 7. 错误处理

| 场景 | 行为 |
|------|------|
| `USAGE_DIR` 不存在 | `mkdir(parents=True, exist_ok=True, mode=0o700)`；不抛 |
| iCloud 离线 / 文件锁 / 磁盘满 | callback 内 try/except，stderr 一行警告，`chat()` 正常返回 |
| `litellm.completion_cost()` 抛 / 返回 None | `cost_usd = null`，继续记录 |
| `response.usage` 不存在（极端 provider） | `input_tokens / output_tokens = null`，继续 |
| stream 调用 | callback 在 stream 结束时由 litellm 触发；`stream=true` 字段标识；usage 仍能拿到 |
| `LLM_USAGE_DIR` 指向不可写路径 | 第一次写入失败，stderr 警告，后续每次仍尝试（不缓存失败状态）|
| `llm-stats` 读到损坏 JSON 行 | skip，stderr 提示 `file:line`，继续读其他行 |
| `llm-stats` 在 USAGE_DIR 不存在时跑 | 提示"还没有日志，跑一次 `chat()` 试试"，exit 0 |
| 同一 process import `model_connector` 多次 | `register()` 幂等，callback 不重复挂 |

## 8. 测试

### 单元测试

`tests/test_usage_log.py`：
- mock `litellm.success_callback` 触发，验证 JSONL 行格式 + 字段完整。
- 验证 `LLM_CALLER` 环境变量优先级。
- 验证 `LLM_LOG_PAYLOAD=0/1` 控制 payload 字段是否出现。
- 验证 cost 算不出时 `cost_usd = null`，其他字段正常。
- 验证 callback 抛异常被吞掉，不影响主流程。
- 验证 `register()` 幂等。
- 验证文件权限 `0600`。
- 验证写入失败（mock open 抛 PermissionError）时不抛。

`tests/test_llm_stats.py`：
- 准备多个 fake `*.jsonl` 文件（不同 host）。
- 验证 `--by provider` / `--by caller` / `--by host` 聚合正确。
- 验证 `--since` 时间窗口过滤。
- 验证 `--filter` 精确 + substring 匹配。
- 验证损坏行跳过 + 警告。
- 验证 `--raw` 输出原始 JSONL。

### 手动验收（在一台 Mac 上）

1. `pip install -e .` 装新版本。
2. 在任意目录跑 `python -c "from model_connector import chat; chat('hi', provider='openai')"`。
3. 检查 `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/llm-usage/<host>.jsonl` 多了一行，权限 `0600`。
4. 跑 `llm-stats --since 1h`，看到这次调用。
5. `LLM_CALLER=test python -c "..."`，验证 `caller_script` 字段。
6. `LLM_LOG_PAYLOAD=1 python -c "..."`，验证多了 `prompt` / `completion` 字段。
7. mock 一次失败（错的 model id），验证 `status=error` 行写入。
8. 等其他 Mac iCloud 同步过来后，跨机器跑 `llm-stats --by host`，验证聚合。

## 9. 多项目接入协议

消费方项目**只做一件事**：

```bash
uv add --editable ~/workspace/model_api_connection
# 或 pip install -e ~/workspace/model_api_connection
```

```python
from model_connector import chat
chat("hi", provider="openai")
# 自动记录，不用配置
```

**可选**：cron / launchd / 长期跑的脚本，建议设环境变量给自己署名：

```bash
LLM_CALLER=daily-summary python ~/scripts/daily.py
```

每个消费项目的 `CLAUDE.md` 加一段（模板放到 `model_api_connection/README.md`）：

> ## LLM 调用
> 用 `from model_connector import chat`。所有调用自动记录到本机 iCloud 同步的 `llm-usage/`，可在任意机器跑 `llm-stats` 查询。
> cron / 长期脚本请设 `LLM_CALLER=<task-name>` 便于事后追溯。

## 10. 迁移计划

1. 实现 `usage_log.py` + `tests/test_usage_log.py`。提交。
2. `model_connector.py` 追加 `register()` import。提交。
3. 实现 `cli/llm_stats.py` + `tests/test_llm_stats.py`。提交。
4. `pyproject.toml` 加 console script + 包配置。提交。
5. 更新 `README.md` 加"LLM 用量监控"章节。提交。
6. 本 Mac 上 `pip install -e .`，跑场景 A-E 验收一遍。
7. 确认 iCloud 容器目录已建出来后，到其他 3 台 Mac 上 `git pull && pip install -e .`。
8. 跑 24-72h，确认 4 台机器都在写、`llm-stats` 跨机器查询能看到全集。

**与 1P 密钥同步 / singleton bug 修复的关系：**
- 三块改动**完全正交**：1P 改密钥加载路径，usage-log 加 callback，singleton 改 `get_connector` 行为。
- 各自独立 branch、独立 PR、独立 merge 顺序。
- 唯一交集是 `model_connector.py`：1P 改 `load_dotenv` 那行，usage-log 在 import 段尾追加 1 行 `register()`，singleton 改 `get_connector` 函数体——三处不冲突。任意顺序合都不会冲突，最多手工 resolve 一个 import 顺序。

## 11. 验收标准

- 在任意 Mac、任意 cwd 跑 `from model_connector import chat; chat('ping', provider='openai')`，对应 `~/.../llm-usage/<host>.jsonl` 多一行有效 JSON。
- 行权限 `0600`，目录权限 `0700`。
- 同 process 多次 `import model_connector` 不会让 callback 重复挂钩（同一调用只记一行）。
- 故意把 `LLM_USAGE_DIR` 设到 `/dev/null/x`（不可写路径），`chat()` 仍正常返回；stderr 有警告。
- 故意 mock litellm 抛异常，`status=error` 行被写入。
- `LLM_LOG_PAYLOAD=1` 时新增 `prompt` + `completion` 字段；不设时这两字段不出现。
- 在另一台 Mac 上 iCloud 同步后，`llm-stats --by host` 能同时看到本机和远端的 host。
- `llm-stats --filter provider=siliconflow --since 36h --by caller` 能定位"哪个脚本在跑 SiliconFlow"——即原始痛点的反向验证。
- 全部 `tests/` 通过。
- model_api_connection git 历史、工作树、任何提交文件里都没有真实 prompt 内容。

## 12. 待定问题

- 无阻塞项。回头再看：
  - **Mac Mini 上线后是否切到 Tailscale + 中心 SQLite？** 决定标准：iCloud 同步延迟在事故场景下（24-48h 后排查）够不够用。够用就不切。
  - **`llm-stats` 要不要加 `--export csv` / `--export sqlite`？** 暂时用 `--raw | jq` 兜底；真有需求再加。
  - **要不要支持给 `chat()` 加 `tags=["batch", "experiment-x"]` 参数？** YAGNI，等真有"实验对比"需求再加 schema 字段。
  - **iCloud 容器换路径**（比如想从 Obsidian 容器搬出来独立）：用 `LLM_USAGE_DIR` 环境变量切换即可，不改代码。

## 13. 范围外（另行处理）

- **实时告警**（launchd 日报、阈值通知到 Lark / 邮件）—— v2 单独 spec。
- **中心化日志服务**（Mac Mini 当 hub、Tailscale 写入）—— Mac Mini 装好系统后单独评估。
- **1Password 密钥同步改造** —— 见 `2026-04-19-1p-key-sync-redesign.md`，独立 PR。
- **`get_connector()` singleton bug 修复 + `chat(raw=True)` 支持** —— 与本议题无关，独立 PR。
