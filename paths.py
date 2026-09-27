"""Shared filesystem path constants for model_api_connection."""

from pathlib import Path

# Provider registry lives next to this module.
CONFIG_PATH = Path(__file__).parent / "model_connector" / "models_config.json"
