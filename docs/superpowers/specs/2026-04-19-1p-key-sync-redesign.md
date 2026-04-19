# Model API Connection - 1Password Key Sync Redesign

**Date:** 2026-04-19
**Status:** Approved (brainstorm phase)
**Owner:** xuche

---

## 1. Problem

Model API Connection (`~/workspace/model_api_connection`) is meant to be the single LLM gateway for all local projects, but the current setup has three unresolved issues:

1. **Keys are not portable.** `python-dotenv` loads `.env` from the caller's CWD, not from this repo. Consumer projects that `pip install -e` the connector do not automatically inherit keys unless each project duplicates `.env` or the user happens to run from this directory.
2. **No unattended (cron / launchd) support.** The user plans to run scheduled LLM jobs on a Mac Mini. The current flow depends on an ambient shell environment that cron does not provide.
3. **Keys live only in scattered files.** No human-readable source of truth. Rotating a key means editing N files across N machines; there is no UI to look up "what is my current OpenAI key?".

Additional context: the user owns 3+ personal Macs plus a work Mac Air, with a Mac Mini being deployed as a home server. All need the same keys. The user has just subscribed to 1Password.

## 2. Goals

- **Single source of truth for keys** that is human-browsable (1Password UI).
- **Zero-friction consumption** for Python projects: `from model_connector import chat` just works, regardless of CWD.
- **Cron / launchd compatible**: scheduled jobs do not require interactive unlock.
- **Cross-machine**: new Mac can be onboarded in under 10 minutes.
- **Safe defaults**: keys never committed to git, local files `chmod 600`.

## 3. Non-Goals

- Pluggable key backends (env var / Keychain / 1P / Vault all in one connector) — YAGNI.
- 1Password Connect self-hosted server — overkill for personal use.
- 1Password Service Accounts (requires 1P Business subscription) — the local-cache pattern gives us the same end result without the cost.
- Automatic key rotation schedule — manual is fine, rotation frequency is low.
- Encrypted local cache (age / gpg around `keys.env`) — FileVault + `chmod 600` is sufficient; an additional encryption layer would need a local private key anyway, adding complexity with no real security gain.
- Personal-profile / user-context injection into prompts — tracked as a separate concern, handled via `~/.claude/CLAUDE.md` imports.
- Shell CLI (`llm chat ...`) — deferred until a non-Python consumer actually needs it.

## 4. Architecture

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
                 | op read  (on demand: bootstrap / rotation)
                 v
+-----------------------------------------+
|  ~/.config/llm/keys.env (chmod 600)     |
|  OPENAI_API_KEY=sk-...                  |
|  ANTHROPIC_API_KEY=sk-ant-...           |
|  ...                                    |
+-----------------------------------------+
                 |
                 | load_dotenv (fixed path, CWD-independent)
                 v
+-----------------------------------------+
|  Consumer code                          |
|  - from model_connector import chat     |
|  - cron scripts                         |
+-----------------------------------------+
```

### Key design principles

- **1Password is the human source of truth.** All lookups, edits, and rotations happen in the 1P UI.
- **`~/.config/llm/keys.env` is the program source of truth.** The connector only reads this file (plus explicit overrides); it never talks to 1P directly at call time.
- **`llm-sync-keys` is the bridge.** A small command that reads 1Password via `op` and writes the cache. Run on first setup, on key rotation, and on new machine onboarding — nothing else.
- **Daily calls do not touch 1Password.** Cron jobs, interactive Python, and tests all read the cache file only.

## 5. Components

### 5.1 1Password Vault Structure

User manually creates (already done):

- Vault name: `llmkeys`
- Items (each with a `credential` field holding the API key):
  - `OpenAI`
  - `Anthropic`
  - `Gemini`
  - `SiliconFlow`
  - `Poe`

Item type: **API Credential** (1P built-in type). The key itself is stored in the field exposed as `op://llmkeys/<item>/credential`.

### 5.2 New files

| File | Purpose | Approx. size |
|------|---------|--------------|
| `key_sync.py` | `llm-sync-keys` command — reads 1P via `op`, writes `keys.env` | ~80 lines |
| `paths.py` | Constants: `KEYS_ENV_PATH = Path.home() / ".config/llm/keys.env"` | ~20 lines |
| `tests/test_key_sync.py` | Unit tests for sync (mock `op`) | ~100 lines |

### 5.3 Modified files

**`model_connector.py`**
- Load `~/.config/llm/keys.env` automatically at module import time (override-capable).
- Fix singleton bug: `get_connector(**kwargs)` currently rebuilds the singleton every time kwargs are passed because of `_default_connector is None or kwargs`. New behavior: cache per kwargs-hash, or rebuild only when kwargs differ.
- Add `raw: bool = False` parameter to `chat()` — when true, return the full litellm response object instead of just `.choices[0].message.content`. Needed for tool-use handling (the current code swallows `tool_calls`).
- Improved error message when keys.env is missing: point at `llm-sync-keys`.
- Public API (`__all__`) stays unchanged; existing callers keep working.

**`models_config.json`**
- Add per-provider `op_reference` field:
  ```json
  "openai": {
    "api_key_env": "OPENAI_API_KEY",
    "op_reference": "op://llmkeys/OpenAI/credential",
    "default_model": "gpt-4o",
    "models": { ... }
  }
  ```
- `key_sync.py` reads this field to know what to fetch from 1P.
- If a provider omits `op_reference`, `llm-sync-keys` skips it (allows mixed-source setups).

**`pyproject.toml`**
- Add console script:
  ```toml
  [project.scripts]
  llm-sync-keys = "key_sync:main"
  ```
- Keep existing `py-modules` and optional-deps sections.

**`README.md`**
- Replace `.env` setup section with the 1Password + `llm-sync-keys` flow.
- Switch install guidance from `pip install -e .` to `uv add --editable <path>` (keep a pip fallback line for legacy).
- Add a new "Bootstrapping a new Mac" mini-section listing the 5-minute checklist.

**`.env.example`** — delete. Its role is superseded by `llmkeys` in 1P plus `llm-sync-keys --help`.

### 5.4 `llm-sync-keys` behavior

```
$ llm-sync-keys
[1Password] Authenticating...   (Touch ID prompt if needed)
- OpenAI        op://llmkeys/OpenAI/credential         -> OPENAI_API_KEY
- Anthropic     op://llmkeys/Anthropic/credential      -> ANTHROPIC_API_KEY
- Gemini        op://llmkeys/Gemini/credential         -> GEMINI_API_KEY
- SiliconFlow   op://llmkeys/SiliconFlow/credential    -> SILICONFLOW_API_KEY
- Poe           op://llmkeys/Poe/credential            -> POE_API_KEY

Wrote 5 keys to ~/.config/llm/keys.env (chmod 600).

$ llm-sync-keys --dry-run
(prints what would be fetched, does not call op or write file)

$ llm-sync-keys --provider openai
(fetches only one provider, useful after rotating a single key)
```

Implementation notes:
- Invoke `op` as a subprocess (`subprocess.run(["op", "read", ref], capture_output=True, text=True)`).
- On missing `op`: print install hint (`brew install 1password-cli`), exit 1.
- On unauthenticated `op` (error text contains "not signed in"): print the "enable CLI integration" hint with link, exit 1.
- On any failed item: print which one failed and continue with the rest; exit non-zero at the end if any failed.
- Write to a temp file then atomic-rename to the final path, so a failed sync never leaves a half-written file.
- Always `chmod 600` on the final file.
- `~/.config/llm/` is created if absent, with `0700` permissions.

## 6. Data Flow

**Scenario A: Interactive Python in any project**
```
$ cd ~/workspace/some-other-project
$ python -c "from model_connector import chat; print(chat('hi', provider='openai'))"
-> model_connector at import time: load_dotenv("~/.config/llm/keys.env")
-> chat() resolves api_key from env (now populated), calls litellm, returns
```

**Scenario B: cron / launchd**
```
(launchd) run /usr/bin/python3 ~/scripts/daily-summarize.py
-> script imports model_connector
-> same load_dotenv, same path, no user interaction
-> runs to completion
```

**Scenario C: Key rotation**
```
1. Rotate key at provider dashboard (e.g., OpenAI Settings -> API keys)
2. Paste new key into 1P item "llmkeys/OpenAI"
3. On each active Mac:  llm-sync-keys --provider openai
4. Next call uses new key automatically
```

**Scenario D: New Mac onboarding**
```
1. Install: brew install 1password 1password-cli uv
2. Sign in to 1P app; enable Settings -> Developer -> Integrate with 1Password CLI
3. Clone the workspace if needed, or `uv add --editable` from an existing path
4. Run: llm-sync-keys          (Touch ID, fetches all)
5. Verify: python -c "from model_connector import chat; print(chat('ping', provider='openai'))"
```

## 7. Error Handling

| Situation | Behavior |
|-----------|----------|
| `~/.config/llm/keys.env` absent at connector init | Do not raise yet; let `chat()` hit the existing "API key not found" path, but with an amended message: "... or run `llm-sync-keys` to populate cache." |
| `keys.env` present but missing a specific key | Same as current: clear error naming the missing env var. |
| `op` CLI not installed | `llm-sync-keys` prints `brew install 1password-cli`, exits 1. |
| `op` CLI not authenticated | `llm-sync-keys` prints the enable-CLI-integration steps, exits 1. |
| `op read` fails for one item | Log, skip, continue; exit non-zero at end. |
| litellm API call fails | Pass through (no new swallowing). |

## 8. Testing

- **Unit tests (`tests/test_key_sync.py`)**: mock `subprocess.run` to simulate various `op` behaviors — success, missing binary, unauthenticated, partial failure. Verify the output file is written with mode `0600` and atomic rename is used.
- **Existing `tests/` stays green**: the integration tests only require the relevant `*_API_KEY` env vars to be set; they do not care whether the value came from `keys.env` or a real shell env.
- **Manual acceptance check on one Mac**:
  1. Populate 1P vault with placeholder test keys
  2. Run `llm-sync-keys`
  3. Confirm `~/.config/llm/keys.env` exists, has `0600`, contains the expected variables
  4. Run `python -c "from model_connector import chat; print(chat('ping', provider='openai'))"` from an unrelated CWD
  5. Rotate one key in 1P, rerun `llm-sync-keys --provider openai`, confirm updated

## 9. Multi-Project Consumption Protocol

Consumer projects do exactly two things:

**Install (once):**
```
uv add --editable ~/workspace/model_api_connection
```

**Use:**
```python
from model_connector import chat
response = chat("hello", provider="openai")
```

No `.env`, no environment setup, no PATH changes, no key duplication.

Each consumer project's `CLAUDE.md` gets a short "LLM Calls" section (copy-paste template provided in `model_api_connection/README.md`) so that any Claude / agent working in that project knows the import pattern immediately.

## 10. Migration Plan

Order matters because consumer projects must not break mid-migration.

1. Populate 1Password `llmkeys` vault with all 5 current keys (user action, done outside this project).
2. Implement `paths.py`, `key_sync.py`, `tests/test_key_sync.py`, update `pyproject.toml`. Commit.
3. Add `op_reference` to `models_config.json`. Commit.
4. Update `model_connector.py`: auto-load from fixed path, fix singleton bug, add `raw=True`, improved errors. Commit.
5. Run `llm-sync-keys` on this Mac. Delete the old in-repo `.env` only after confirming the cache works.
6. Update `README.md` and remove `.env.example`. Commit.
7. On each other Mac: bootstrap flow (Scenario D above).
8. For each consumer project: `uv add --editable ...`, remove any local `.env` duplication, verify.

## 11. Acceptance Criteria

- From any directory on this Mac, `python -c "from model_connector import chat; print(chat('ping', provider='openai'))"` succeeds without environment setup.
- `launchctl` can run a Python script that calls `chat(...)` and completes without interactive input.
- Deleting `~/.config/llm/keys.env` breaks calls; running `llm-sync-keys` restores them.
- `~/.config/llm/keys.env` has mode `0600` after sync.
- No API keys in the model_api_connection git history, working tree, or any committed file.
- `tests/` passes.

## 12. Open Questions

- None blocking. Revisit later:
  - Should `llm-sync-keys` offer a `--watch` mode that re-runs on a schedule? (Probably not — rotations are rare.)
  - Should we add a "last rotated on" metadata line to `keys.env`? (Nice-to-have, not now.)
  - Should consumer projects pin to a specific commit of model_api_connection, or stay on `main`? (Default: editable install from `main` for personal flexibility.)

## 13. Out of Scope (Tracked Elsewhere)

- Personal profile injection (devices, role, work context) into every LLM call — handled via Claude Code's `~/.claude/CLAUDE.md` `@` imports, separate workstream.
- Claude Code subscription token reuse for scheduled LLM jobs — flagged in CLAUDE.md; revisit per job.
