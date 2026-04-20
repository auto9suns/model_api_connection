"""llm-sync-keys: sync API keys from 1Password to ~/.config/llm/keys.env."""

from __future__ import annotations

import json
from pathlib import Path


def load_providers(
    config_path: Path, only: str | None = None
) -> dict[str, tuple[str, str]]:
    """Read models_config.json and return providers that have an op_reference.

    Returns a dict mapping provider name -> (op_reference, api_key_env).
    When `only` is provided, the result contains at most that one provider.
    """
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    result: dict[str, tuple[str, str]] = {}
    for name, spec in cfg.get("providers", {}).items():
        if only is not None and name != only:
            continue
        ref = spec.get("op_reference")
        env_var = spec.get("api_key_env")
        if ref and env_var:
            result[name] = (ref, env_var)
    return result
