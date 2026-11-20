"""R3 keychain fallback for provider API keys — the keychain read is stubbed."""

import os
import subprocess
import sys
import types

import pytest

import _fetch_helpers
import model_connector
from model_connector import keychain

VAR = "FAKE_PROVIDER_API_KEY"
SECRET = "sk-keychain-secret-value"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(VAR, raising=False)
    monkeypatch.delenv("LLM_KEYCHAIN", raising=False)


def _stub(monkeypatch, rc=0, out=SECRET + "\n", exc=None):
    calls = []

    def read(env_var):
        calls.append(env_var)
        if exc is not None:
            raise exc
        return rc, out

    monkeypatch.setattr(keychain, "_read", read)
    return calls


# ── R3 table, 9 rows ──────────────────────────────────────────────────────────

def test_r3_1_env_wins_and_strips(monkeypatch):
    calls = _stub(monkeypatch)
    monkeypatch.setenv(VAR, "  from-env  ")
    monkeypatch.setenv("LLM_KEYCHAIN", "off")  # switch is not consulted
    assert keychain.api_key_from_env_or_keychain(VAR) == ("from-env", None)
    assert calls == []


def test_r3_2_switch_off_is_disabled(monkeypatch):
    calls = _stub(monkeypatch)
    monkeypatch.setenv("LLM_KEYCHAIN", "off")
    assert keychain.api_key_from_env_or_keychain(VAR) == (None, "disabled")
    assert calls == []


def test_r3_2_switch_other_value_is_unset(monkeypatch):
    _stub(monkeypatch)
    monkeypatch.setenv("LLM_KEYCHAIN", "OFF")
    assert keychain.api_key_from_env_or_keychain(VAR) == (SECRET, None)


def test_r3_3_timeout(monkeypatch):
    _stub(monkeypatch, exc=subprocess.TimeoutExpired("security", 5))
    assert keychain.api_key_from_env_or_keychain(VAR) == (None, "timeout")


@pytest.mark.parametrize("exc", [
    PermissionError("sandbox"),
    FileNotFoundError("no security"),
    UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"),
])
def test_r3_4_oserror_or_valueerror_is_error(monkeypatch, exc):
    _stub(monkeypatch, exc=exc)
    assert keychain.api_key_from_env_or_keychain(VAR) == (None, "error")


def test_r3_5_keychain_value_is_stripped(monkeypatch):
    calls = _stub(monkeypatch, out="  " + SECRET + "  \n")
    assert keychain.api_key_from_env_or_keychain(VAR) == (SECRET, None)
    assert calls == [VAR]


@pytest.mark.parametrize("out", ["", "  \n"])
def test_r3_6_rc0_empty_is_missing(monkeypatch, out):
    _stub(monkeypatch, rc=0, out=out)
    assert keychain.api_key_from_env_or_keychain(VAR) == (None, "missing")


def test_r3_7_rc36_is_locked(monkeypatch):
    _stub(monkeypatch, rc=36, out="")
    assert keychain.api_key_from_env_or_keychain(VAR) == (None, "locked")


def test_r3_8_rc44_is_missing(monkeypatch):
    _stub(monkeypatch, rc=44, out="")
    assert keychain.api_key_from_env_or_keychain(VAR) == (None, "missing")


@pytest.mark.parametrize("rc", [1, 2, 45, 255])
def test_r3_9_other_rc_is_error(monkeypatch, rc):
    _stub(monkeypatch, rc=rc, out=SECRET)
    assert keychain.api_key_from_env_or_keychain(VAR) == (None, "error")


def test_empty_env_var_name_never_reads_keychain(monkeypatch):
    calls = _stub(monkeypatch)
    assert keychain.api_key_from_env_or_keychain("") == (None, "missing")
    assert calls == []


# ── invariant: environment untouched ──────────────────────────────────────────

def test_environ_unchanged_after_keychain_hit(monkeypatch):
    _stub(monkeypatch)
    before = dict(os.environ)
    assert keychain.api_key_from_env_or_keychain(VAR)[0] == SECRET
    assert dict(os.environ) == before
    assert VAR not in os.environ


# ── the real read: argv shape and timeout (subprocess.run stubbed) ────────────

def test_read_calls_absolute_security_with_llm_account(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        return types.SimpleNamespace(returncode=0, stdout=SECRET)

    monkeypatch.setattr(keychain.subprocess, "run", fake_run)
    assert keychain._read(VAR) == (0, SECRET)
    assert seen["argv"][0] == "/usr/bin/security"
    assert seen["argv"][1] == "find-generic-password"
    assert ["-a", "llm", "-s", VAR] == seen["argv"][2:6]
    assert seen["kw"]["timeout"] == 5


# ── call sites ────────────────────────────────────────────────────────────────

CFG = {"providers": {"fake": {"api_key_env": VAR, "default_model": "m",
                              "models": {"m": "fake/m"}}}}


def _connector(tmp_path):
    import json
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(CFG))
    return model_connector.LLMConnector(config_path=p)


def test_get_api_key_uses_keychain_without_touching_environ(monkeypatch, tmp_path):
    _stub(monkeypatch)
    llm = _connector(tmp_path)
    assert llm._get_api_key("fake", CFG["providers"]["fake"]) == SECRET
    assert VAR not in os.environ


def test_get_api_key_override_still_first(monkeypatch, tmp_path):
    calls = _stub(monkeypatch)
    llm = _connector(tmp_path)
    llm._api_keys_override["fake"] = "explicit"
    assert llm._get_api_key("fake", CFG["providers"]["fake"]) == "explicit"
    assert calls == []


def test_get_api_key_error_carries_reason_not_value(monkeypatch, tmp_path):
    _stub(monkeypatch, rc=36, out=SECRET)
    llm = _connector(tmp_path)
    with pytest.raises(EnvironmentError) as ei:
        llm._get_api_key("fake", CFG["providers"]["fake"])
    msg = str(ei.value)
    assert VAR in msg and "locked" in msg and "keyinit status llm" in msg
    assert SECRET not in msg


def test_fetch_provider_uses_keychain(monkeypatch):
    _stub(monkeypatch)
    seen = {}
    monkeypatch.setattr(_fetch_helpers, "_fetch_openai",
                        lambda key, base_url=None: seen.setdefault("key", key) and [])
    assert _fetch_helpers.fetch_provider("fake", {"api_key_env": VAR}) == []
    assert seen["key"] == SECRET
    assert VAR not in os.environ


def test_fetch_provider_skip_message_has_reason(monkeypatch):
    _stub(monkeypatch, rc=44, out="")
    assert _fetch_helpers.fetch_provider("fake", {"api_key_env": VAR}) == (
        f"[SKIP] {VAR} not available (missing)"
    )


def test_video_gemini_uses_keychain(monkeypatch, tmp_path):
    import video_connector

    _stub(monkeypatch)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    seen = {}
    fake = types.ModuleType("gemini_uploader")
    fake.upload_video = lambda path, key: seen.setdefault("key", key) and "files/x"
    monkeypatch.setitem(sys.modules, "gemini_uploader", fake)
    msgs = video_connector._messages_gemini_file_api(tmp_path / "v.mp4", "p")
    assert seen["key"] == SECRET
    assert "GEMINI_API_KEY" not in os.environ
    assert msgs[0]["content"][0]["video_url"]["url"] == "files/x"


def test_video_gemini_error_has_reason(monkeypatch, tmp_path):
    import video_connector

    _stub(monkeypatch, exc=subprocess.TimeoutExpired("security", 5))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(EnvironmentError) as ei:
        video_connector._messages_gemini_file_api(tmp_path / "v.mp4", "p")
    assert "GEMINI_API_KEY" in str(ei.value) and "timeout" in str(ei.value)
