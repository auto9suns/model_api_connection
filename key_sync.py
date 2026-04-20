"""llm-sync-keys: sync API keys from 1Password to ~/.config/llm/keys.env."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path


class OpError(RuntimeError):
    """Raised when `op` CLI returns a non-zero exit code."""


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


def fetch_key(op_reference: str) -> str:
    """Fetch a single credential from 1Password via the `op` CLI.

    Requires `op` CLI to be installed and in PATH.
    Raises OpError if `op` exits non-zero.
    """
    # nosec B607: `op` is a standard CLI tool required in PATH
    result = subprocess.run(
        ["op", "read", op_reference],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise OpError(result.stderr.strip() or "op read failed")
    return result.stdout.strip()


def write_keys_env(keys: dict[str, str], target: Path) -> None:
    """Atomically write {env_var: value} pairs to target (mode 0600).

    The parent directory is created with mode 0700 if needed.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)

    fd, tmp_name = tempfile.mkstemp(
        prefix=".keys.env.", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for env_var, value in keys.items():
                f.write(f"{env_var}={value}\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
