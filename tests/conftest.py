"""Test isolation: never let a test fall through to the real keychain."""

import os

os.environ["LLM_KEYCHAIN"] = "off"
