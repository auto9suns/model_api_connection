"""LLM configuration dataclass and loaders for caller projects."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class LLMConfig:
    """Parsed LLM configuration.

    provider and model are validated non-empty strings.
    extra holds all remaining fields from the source dict, verbatim.
    """

    provider: str
    model: str
    extra: dict = field(default_factory=dict)


def parse_llm_config(data: dict) -> LLMConfig:
    """Construct LLMConfig from a dict, validating required fields.

    Suitable for extracting the llm: section from a larger config
    (e.g. a YAML business config already loaded in memory).

    Args:
        data: dict containing at minimum "provider" and "model" keys.

    Returns:
        LLMConfig with provider, model, and extra (all other keys).

    Raises:
        ValueError: if provider or model is missing, non-string, or empty.
    """
    for field_name in ("provider", "model"):
        if field_name not in data:
            raise ValueError(f"llm config missing required field: {field_name}")
        val = data[field_name]
        if not isinstance(val, str) or not val.strip():
            raise ValueError(
                f"{field_name} must be a non-empty string, got: {val!r}"
            )

    extra = {k: v for k, v in data.items() if k not in ("provider", "model")}
    return LLMConfig(provider=data["provider"], model=data["model"], extra=extra)


def load_llm_config(path: str | Path = "llm.json") -> LLMConfig:
    """Read an llm.json file and return a parsed LLMConfig.

    Default path is ./llm.json relative to the current working directory.
    Does not search parent directories.

    Args:
        path: path to the JSON file (default "llm.json").

    Returns:
        LLMConfig parsed from the file contents.

    Raises:
        FileNotFoundError: if the file does not exist, with message
            "llm.json not found at <absolute-path>".
        json.JSONDecodeError: if the file content is not valid JSON.
        ValueError: if required fields are missing or invalid.
    """
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"llm.json not found at {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    return parse_llm_config(data)
