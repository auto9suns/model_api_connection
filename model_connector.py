"""
Universal LLM API Connector (powered by litellm)
==================================================
Supports: OpenAI, Anthropic, Gemini, SiliconFlow, Poe, and any OpenAI-compatible provider.

Usage:
    from model_connector import LLMConnector

    llm = LLMConnector()

    # Basic call
    response = llm.chat("你好", provider="siliconflow", model="deepseek-v3")

    # Streaming
    for chunk in llm.chat("解释量子纠缠", provider="anthropic", model="sonnet-4.6", stream=True):
        print(chunk, end="", flush=True)

    # Multi-turn
    messages = [
        {"role": "user", "content": "我叫小明"},
        {"role": "assistant", "content": "你好，小明！"},
        {"role": "user", "content": "我叫什么名字？"},
    ]
    response = llm.chat(messages, provider="openai", model="gpt-4o")

    # Function calling / Tool use
    tools = [{"type": "function", "function": {
        "name": "get_weather", "description": "Get weather for a city",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    }}]
    response = llm.chat("北京天气怎么样？", provider="openai", tools=tools)

    # Use default model for provider
    response = llm.chat("Hi", provider="openai")
"""

import json
import os
from pathlib import Path
from typing import Iterator

import litellm

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


__all__ = ["LLMConnector", "chat", "get_connector", "strip_think_stream"]

CONFIG_PATH = Path(__file__).parent / "models_config.json"


# ── Main connector ─────────────────────────────────────────────────────────────

class LLMConnector:
    """
    Universal connector for multiple LLM providers.

    Parameters
    ----------
    config_path : str | Path, optional
        Path to models_config.json. Defaults to the file next to this module.
    api_keys : dict, optional
        Override API keys without using env vars.
        Example: {"openai": "sk-...", "siliconflow": "sf-..."}
    """

    def __init__(self, config_path: str | Path | None = None, api_keys: dict | None = None):
        cfg_path = Path(config_path) if config_path else CONFIG_PATH
        with open(cfg_path, "r", encoding="utf-8") as f:
            self._config = json.load(f)
        self._api_keys_override = api_keys or {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def chat(
        self,
        messages: str | list[dict],
        *,
        provider: str,
        model: str | None = None,
        stream: bool = False,
        **kwargs,
    ) -> str | Iterator[str]:
        """
        Send a chat request via litellm.

        Parameters
        ----------
        messages : str or list of dicts
            Plain string, or full message list:
            [{"role": "user"|"assistant"|"system", "content": "..."}]
        provider : str
            Provider key from models_config.json.
        model : str, optional
            Model alias as listed in models_config.json.
            Uses the provider's default_model if omitted.
        stream : bool
            Return a text-chunk generator instead of a full string.
        **kwargs
            Forwarded to litellm.completion (temperature, max_tokens, tools, etc.).
        """
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        prov_cfg = self._get_provider_config(provider)
        model_id = self._resolve_model(prov_cfg, model)
        api_key = self._get_api_key(provider, prov_cfg)

        litellm_kwargs = {
            "model": model_id,
            "messages": messages,
            "stream": stream,
            "api_key": api_key,
            **kwargs,
        }
        if "base_url" in prov_cfg:
            litellm_kwargs["api_base"] = prov_cfg["base_url"]

        response = litellm.completion(**litellm_kwargs)

        if stream:
            return self._iter_stream(response)
        return response.choices[0].message.content

    def list_providers(self) -> list[str]:
        """Return all configured provider names."""
        return list(self._config["providers"].keys())

    def list_models(self, provider: str) -> list[str]:
        """Return model aliases for a provider."""
        return list(self._get_provider_config(provider).get("models", {}).keys())

    def default_model(self, provider: str) -> str:
        """Return the default model alias for a provider."""
        return self._get_provider_config(provider).get("default_model", "")

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get_provider_config(self, provider: str) -> dict:
        try:
            return self._config["providers"][provider]
        except KeyError:
            available = ", ".join(self._config["providers"])
            raise ValueError(f"Unknown provider '{provider}'. Available: {available}")

    def _resolve_model(self, prov_cfg: dict, model: str | None) -> str:
        model_name = model or prov_cfg.get("default_model")
        if not model_name:
            raise ValueError("No model specified and no default_model configured.")
        models = prov_cfg.get("models", {})
        if model_name in models:
            return models[model_name]
        return model_name

    def _get_api_key(self, provider: str, prov_cfg: dict) -> str:
        if provider in self._api_keys_override:
            return self._api_keys_override[provider]
        env_var = prov_cfg.get("api_key_env", "")
        key = os.environ.get(env_var, "")
        if not key:
            raise EnvironmentError(
                f"API key for '{provider}' not found. "
                f"Set the '{env_var}' environment variable or pass "
                f"api_keys={{'{provider}': '...'}} to LLMConnector()."
            )
        return key

    @staticmethod
    def _iter_stream(response) -> Iterator[str]:
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content


# ── Module-level shortcuts ─────────────────────────────────────────────────────

_default_connector: LLMConnector | None = None


def get_connector(**kwargs) -> LLMConnector:
    """Return a module-level singleton LLMConnector (lazily initialized)."""
    global _default_connector
    if _default_connector is None or kwargs:
        _default_connector = LLMConnector(**kwargs)
    return _default_connector


def chat(
    messages: str | list[dict],
    *,
    provider: str,
    model: str | None = None,
    stream: bool = False,
    **kwargs,
) -> str | Iterator[str]:
    """Module-level shortcut — no need to instantiate LLMConnector."""
    return get_connector().chat(messages, provider=provider, model=model, stream=stream, **kwargs)


# ── Streaming utilities ────────────────────────────────────────────────────────

def strip_think_stream(chunks: Iterator[str]) -> Iterator[str]:
    """Remove <think>...</think> reasoning blocks from a streaming response.

    Useful with reasoning models (DeepSeek-R1, Kimi-K2.5) that output
    chain-of-thought wrapped in <think> tags before the final answer.
    """
    OPEN, CLOSE = "<think>", "</think>"
    buf, inside = "", False
    for chunk in chunks:
        buf += chunk
        while True:
            tag = CLOSE if inside else OPEN
            idx = buf.find(tag)
            if idx == -1:
                safe = max(0, len(buf) - len(tag) + 1)
                if not inside and safe > 0:
                    yield buf[:safe]
                buf = buf[safe:]
                break
            if not inside:
                yield buf[:idx]
            buf = buf[idx + len(tag):]
            inside = not inside
    if buf and not inside:
        yield buf
