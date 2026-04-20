"""llm-sync-keys: sync API keys from 1Password to ~/.config/llm/keys.env."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from paths import CONFIG_PATH, KEYS_ENV_PATH


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
    result = subprocess.run(  # nosec B607
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
    os.chmod(target.parent, 0o700)  # nosec B103  # nosemgrep

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


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="llm-sync-keys",
        description="Sync LLM API keys from 1Password into ~/.config/llm/keys.env.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List what would be fetched without calling op or writing the cache.",
    )
    parser.add_argument(
        "--provider",
        help="Only sync the named provider (matches a key in models_config.json).",
    )
    return parser.parse_args(argv)


_AUTH_ERROR_MARKERS = ("not signed in", "you are not signed", "authenticate")


def _read_existing_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    providers = load_providers(CONFIG_PATH, only=args.provider)
    if not providers:
        print(
            "No provider with 'op_reference' configured"
            + (f" for --provider {args.provider}" if args.provider else ""),
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        for name, (ref, env_var) in providers.items():
            print(f"- {name:12s} {ref} -> {env_var}")
        return 0

    if shutil.which("op") is None:
        print(
            "Error: 'op' CLI not installed.\n"
            "Install: brew install 1password-cli",
            file=sys.stderr,
        )
        return 1

    fetched: dict[str, str] = {}
    failures: list[str] = []
    for name, (ref, env_var) in providers.items():
        try:
            fetched[env_var] = fetch_key(ref)
            print(f"  OK  {name:12s} -> {env_var}")
        except OpError as exc:
            msg = str(exc).lower()
            if any(marker in msg for marker in _AUTH_ERROR_MARKERS):
                print(
                    "Error: 'op' CLI is not authenticated.\n"
                    "Open 1Password app -> Settings -> Developer -> "
                    "enable 'Integrate with 1Password CLI'",
                    file=sys.stderr,
                )
                return 1
            print(f"  FAIL {name:12s} {exc}", file=sys.stderr)
            failures.append(name)

    if fetched:
        merged = _read_existing_env(KEYS_ENV_PATH) if args.provider else {}
        merged.update(fetched)
        write_keys_env(merged, KEYS_ENV_PATH)
        print(f"\nWrote {len(merged)} keys to {KEYS_ENV_PATH} (chmod 600).")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
