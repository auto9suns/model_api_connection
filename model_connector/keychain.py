"""R3 key lookup: env first, then the macOS keychain (-a llm -s <env var>).

The value is returned to the caller only; it is never written to os.environ.
"""

import os
import subprocess

KEYCHAIN_SWITCH = "LLM_KEYCHAIN"
_TIMEOUT_SECONDS = 5

_HINTS = {
    "locked": "keychain is locked; retry from a local GUI session or after "
              "`security unlock-keychain`",
    "missing": "run `keyinit status llm`; ask Father to run `! keyinit sync llm` if it's missing",
}


def _read(env_var: str) -> tuple[int, str]:
    """Test seam: the only place that spawns `security`."""
    proc = subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-a", "llm", "-s", env_var, "-w"],
        capture_output=True, text=True, timeout=_TIMEOUT_SECONDS,
    )
    return proc.returncode, proc.stdout


def api_key_from_env_or_keychain(env_var: str) -> tuple[str | None, str | None]:
    """Return (value, None) on success or (None, reason) on failure."""
    if not env_var:
        return None, "missing"
    env = os.environ.get(env_var, "").strip()
    if env:
        return env, None
    if os.environ.get(KEYCHAIN_SWITCH) == "off":
        return None, "disabled"
    try:
        rc, out = _read(env_var)
    except subprocess.TimeoutExpired:
        return None, "timeout"
    except (OSError, ValueError):
        return None, "error"
    if rc == 0:
        value = out.strip()
        return (value, None) if value else (None, "missing")
    if rc == 36:
        return None, "locked"
    if rc == 44:
        return None, "missing"
    return None, "error"


def failure_hint(reason: str) -> str:
    """Reason plus remedy text, never containing a key value."""
    hint = _HINTS.get(reason)
    return f"{reason}: {hint}" if hint else reason
