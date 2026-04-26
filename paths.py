"""Shared filesystem path constants for model_api_connection."""

from pathlib import Path

# Local cache of API keys (populated by `llm-sync-keys`).
KEYS_ENV_DIR = Path.home() / ".config" / "llm"
KEYS_ENV_PATH = KEYS_ENV_DIR / "keys.env"

# Provider registry lives next to this module.
CONFIG_PATH = Path(__file__).parent / "model_connector" / "models_config.json"
