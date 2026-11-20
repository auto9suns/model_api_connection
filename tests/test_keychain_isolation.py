"""conftest must keep the suite off the real keychain."""

import os


def test_suite_runs_with_keychain_disabled():
    assert os.environ.get("LLM_KEYCHAIN") == "off"
