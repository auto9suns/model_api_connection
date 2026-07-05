# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> This history was reconstructed retroactively (bootstrap) from the git log — the
> project shipped continuously on `main` before formal tagging began.

## [0.5.0] - 2026-04-26
修复非 editable 安装丢失配置文件的打包 bug，收敛模型 key 命名规则，并新增 LLMConfig 配置解析助手 API。

### Added
- `model_connector/config.py`：新增 `LLMConfig` 冻结 dataclass、`parse_llm_config()`、`load_llm_config()`，并从 `__init__.py` 重新导出 —— 消费方项目可直接 `from model_connector import load_llm_config`，标准化 `llm.json` 的 `provider`+`model` schema，无需各自重复解析逻辑。
- `LLMConfig`/`parse_llm_config`/`load_llm_config` 的单元测试（文件读取 + 错误路径覆盖）—— 保证新 helper API 的行为在未来重构中不被破坏。

### Changed
- `model_connector` 从单文件模块重构为 package，`pyproject.toml` 声明其为 package —— 修复非 editable 安装（如 git-source 依赖）时 `models_config.json` 未被打进 wheel、运行时报 "config not found" 的 bug。
- 模型 key 统一为 `{brand}-{tier}-{version}` 命名规范（`claude-*`/`gemini-*` 前缀）—— 消除此前 anthropic/gemini/meai key 风格不统一的问题，例如 poe 的 `gemini-3-pro` 调整为 `gemini-pro-3`。
- `LLMConfig.extra` 字段类型收紧为 `dict[str, Any]` —— 提升类型检查的准确性，避免调用方误用弱类型字段。
- README/示例/docstring 同步更新为新 key 命名 —— 消除文档与代码之间的漂移。

### Fixed
- litellm 升级到 1.83.14，修复 GHSA-xqmj-j6mv-4862 —— 消除已知安全漏洞。

## [0.4.1] - 2026-04-24
修复依赖安全漏洞并澄清 1Password CLI 前置配置步骤。

### Changed
- README `llm-sync-keys` 前置条件拆成 4 步编号清单，并把"桌面 app 集成"前置为首选路径，加入不要走 `op account add` 手动加账号的警告 —— 修复原文档易让人被 Y/N 提示带偏、卡在 34 位 Secret Key 上的问题。

### Fixed
- python-dotenv 升级到 1.2.2，修复 CVE-2026-28684（`set_key()`/`unset_key()` symlink-following 漏洞）—— 本项目仅只读调用 `load_dotenv()` 实际不受影响，升级主要为了过 Trivy 扫描并与上游保持同步。

## [0.4.0] - 2026-04-21
引入 1Password 单一可信源密钥同步机制，新增 meai 中转 provider，并统一模型 key 命名规范。

### Added
- `key_sync.py` / `llm-sync-keys` CLI：从 1Password vault `llmkeys` 同步 API key 到固定路径 `~/.config/llm/keys.env`（权限 600），支持原子写入 + 部分失败处理 —— 密钥加载不再依赖 CWD 下的 `.env` 文件，跨目录调用也能正确取到 key。
- `paths.py` 共享路径常量（`KEYS_ENV_PATH`/`CONFIG_PATH`）—— 统一密钥缓存和配置文件位置，消除多处硬编码路径的不一致风险。
- 新增 meai 中转站 provider（OpenAI 兼容协议），收录 glm-5/glm-5.1/claude-sonnet-4-6/claude-opus-4-7/gemini-3-flash 5 个模型 —— 扩展了一条中转商的可用模型接入渠道。

### Changed
- `load_dotenv` 改为 `override=True`，确保 `~/.config/llm/keys.env` 始终优先于 shell 环境变量 —— 修复同步新 key 后 shell 里旧 key 仍被使用导致 auth 失败的问题。
- 统一模型 key 命名规范为全小写连字符、去除品牌冗余前缀 —— 消除 gemini/siliconflow/poe/meai 各自风格不一致的别名，降低使用时的记忆负担。
- meai `base_url` 从 IP 地址换成正式域名 —— 提升生产环境下的可维护性和可信度。
- README 补充 meai provider 说明，`llm-sync-keys`/`llm-stats` 命令统一加 `uv run` 前缀 —— 修正未全局安装时直接调用命令报 not found 的文档偏差。

## [0.3.0] - 2026-04-20
新增 LLM 调用用量自动记录与跨机器聚合查询能力，同时修复日志目录的可移植性问题。

### Added
- `usage_log.py`：通过 litellm callback 自动记录每次 `chat()` 调用到 JSONL 文件，消费方项目零改动接入 —— 每次 LLM 调用的 token/成本/延迟从此可追溯，无需在业务代码里手动埋点。
- `llm-stats` CLI：支持 `--since`/`--by`/`--filter`/`--raw`/`--tail`/`--paths` 跨机器聚合查询 —— 排查某个 provider 异常调用或统计成本时，一条命令即可跨设备汇总，无需手动翻 JSONL 文件。
- Poe 配置新增 Claude Haiku 4.5 —— 及时跟进模型上新，消费方无需等待下一次大版本即可用上新模型。

### Changed
- pytest 升级到 9.0.3 —— 修复 CVE-2025-71176，消除已知安全漏洞。

### Fixed
- `_usage_dir()` 改为强制读取 `LLM_USAGE_DIR` 环境变量，移除硬编码的 Obsidian 路径 —— 修复日志目录不可移植的问题，让用量记录能力在任意机器上正常工作，而不是只在作者本机生效。

## [0.2.0] - 2026-04-07
底层切换到 litellm 统一多 Provider 协议，新增 Poe 支持、原生 Tool Use 和视频理解能力。

### Added
- 新增 Poe provider 支持 —— Poe 走标准 OpenAI 兼容格式，零适配成本即可接入。
- 原生 Function Calling / Tool Use（`tools=` 参数透传给 litellm）—— 自动适配各 provider 的工具调用格式差异，调用方无需手写适配层。
- `gemini_uploader.py` 和 `video_connector.py` 模块 —— 提供统一的视频理解接口，支持 Gemini File API 大文件上传和 Qwen base64 内联两种传输策略。

### Changed
- 底层改用 litellm，删除自建 `_OpenAIProvider`/`_AnthropicProvider` 类，代码从约 300 行降至约 170 行 —— 降低多 Provider 适配的维护成本，未来新增 provider 只需改配置。
- SiliconFlow model ID 改为 `openai/` 前缀 + `base_url` —— 解决 litellm 不识别 `siliconflow/` 前缀导致请求路由错误的问题。
- `strip_think_stream` 重写 —— 修复流式输出末尾未闭合 `<think>` 块导致内容截断的边界问题。

### Fixed
- 关闭 asyncio event loop 抑制 litellm 清理时的报错 —— 避免程序退出时打印无害但引起困惑的错误堆栈。
- 抑制 `_fetch_helpers.py` 中 Bandit B310 和 Semgrep 对 urllib urlopen 的误报 —— 让安全扫描通过，不掩盖真正的风险点。

## [0.1.0] - 2026-03-24
首次发布，建立统一的多模型连接器基础能力和可安装的包结构。

### Added
- 初版 `model_connector.py`：统一封装 OpenAI/Anthropic 直连调用与 `models_config.json` 模型注册表 —— 让消费方项目通过一次 import 切换任意 provider，无需分别接入各家 SDK。
- `pyproject.toml` 打包支持，可 `pip install -e .` 安装为独立包 —— 让其他项目能像装普通依赖一样引入，而非复制粘贴源码。
- 公共 API 导出（`__all__`）与 dotenv 自动加载 —— 明确对外契约，调用方无需猜测哪些符号可用。
- pytest 单元测试套件（15 个用例，覆盖配置解析/模型解析/API key/消息格式化）—— 为后续重构提供回归保护网。
- 中文 README，补充公共 API 签名表和 AI Agent 调用指南 —— 降低团队内其他人和 AI 助手接入的上手成本。

### Changed
- 拆分 `fetch_models.py`（412 行 → 167+251 行）为 `_fetch_helpers.py` —— 符合项目文件拆分规范，提升可维护性。
- `requirements.txt` 区分核心依赖与工具依赖 —— litellm 仅工具脚本需要，避免核心运行时引入不必要的重依赖。

[0.5.0]: https://github.com/auto9suns/model_api_connection/releases/tag/v0.5.0
[0.4.1]: https://github.com/auto9suns/model_api_connection/releases/tag/v0.4.1
[0.4.0]: https://github.com/auto9suns/model_api_connection/releases/tag/v0.4.0
[0.3.0]: https://github.com/auto9suns/model_api_connection/releases/tag/v0.3.0
[0.2.0]: https://github.com/auto9suns/model_api_connection/releases/tag/v0.2.0
[0.1.0]: https://github.com/auto9suns/model_api_connection/releases/tag/v0.1.0
