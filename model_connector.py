"""
Universal LLM API Connector
============================
Supports: OpenAI, Anthropic (Claude), Google (Gemini), SiliconFlow (and any OpenAI-compatible provider)

Usage:
    from model_connector import LLMConnector

    llm = LLMConnector()

    # Basic call — model name must match the key in models_config.json exactly
    response = llm.chat("你好", provider="siliconflow", model="deepseek-ai/DeepSeek-V3")

    # Streaming
    for chunk in llm.chat("解释量子纠缠", provider="anthropic", model="claude-sonnet-4-6", stream=True):
        print(chunk, end="", flush=True)

    # Multi-turn
    messages = [
        {"role": "user", "content": "我叫小明"},
        {"role": "assistant", "content": "你好，小明！"},
        {"role": "user", "content": "我叫什么名字？"},
    ]
    response = llm.chat(messages, provider="openai", model="gpt-4o")

    # Use default model for provider
    response = llm.chat("Hi", provider="openai")
"""

import json
import os
from pathlib import Path
from typing import Iterator

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


__all__ = ["LLMConnector", "chat", "get_connector", "strip_think_stream"]

CONFIG_PATH = Path(__file__).parent / "models_config.json"


# ── Provider implementations ───────────────────────────────────────────────────

class _OpenAIProvider:
    """Handles OpenAI-compatible APIs (OpenAI, Gemini, SiliconFlow, etc.)."""

    def __init__(self, api_key: str, base_url: str | None = None):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, **({"base_url": base_url} if base_url else {}))

    def chat(self, messages: list[dict], model: str, stream: bool, **kwargs) -> str | Iterator[str]:
        response = self.client.chat.completions.create(
            model=model, messages=messages, stream=stream, **kwargs
        )
        if stream:
            return self._stream(response)
        return response.choices[0].message.content

    def _stream(self, response) -> Iterator[str]:
        in_reasoning = False
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            has_reasoning = hasattr(delta, "reasoning_content") and delta.reasoning_content
            has_content   = bool(delta.content)

            if has_reasoning:
                if not in_reasoning:
                    yield "<think>"
                    in_reasoning = True
                yield delta.reasoning_content

            if has_content:
                if in_reasoning:
                    yield "</think>"
                    in_reasoning = False
                yield delta.content

        if in_reasoning:
            yield "</think>"


class _AnthropicProvider:
    """Handles Anthropic Claude API."""

    def __init__(self, api_key: str):
        from anthropic import Anthropic
        self.client = Anthropic(api_key=api_key)

    def chat(self, messages: list[dict], model: str, stream: bool, **kwargs) -> str | Iterator[str]:
        system = None
        filtered = []
        for m in messages:
            if m["role"] == "system":
                system = m["content"]
            else:
                filtered.append(m)

        create_kwargs = dict(
            model=model,
            max_tokens=kwargs.pop("max_tokens", 8096),
            messages=filtered,
            **kwargs,
        )
        if system:
            create_kwargs["system"] = system

        if stream:
            return self._stream(create_kwargs)

        response = self.client.messages.create(**create_kwargs)
        return response.content[0].text

    def _stream(self, create_kwargs) -> Iterator[str]:
        with self.client.messages.stream(**create_kwargs) as stream:
            for text in stream.text_stream:
                yield text


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
        self._provider_cache: dict = {}

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
        Send a chat request.

        Parameters
        ----------
        messages : str or list of dicts
            Plain string, or full message list:
            [{"role": "user"|"assistant"|"system", "content": "..."}]
        provider : str
            Provider key from models_config.json ("openai", "anthropic", "gemini", "siliconflow").
        model : str, optional
            Official model name as listed in models_config.json.
            Uses the provider's default_model if omitted.
        stream : bool
            Return a text-chunk generator instead of a full string.
        **kwargs
            Forwarded to the underlying API (temperature, max_tokens, etc.).
        """
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        prov_cfg = self._get_provider_config(provider)
        model_id = self._resolve_model(prov_cfg, model)
        client = self._get_client(provider, prov_cfg)

        return client.chat(messages, model=model_id, stream=stream, **kwargs)

    def list_providers(self) -> list[str]:
        """Return all configured provider names."""
        return list(self._config["providers"].keys())

    def list_models(self, provider: str) -> list[str]:
        """Return official model names for a provider."""
        return list(self._get_provider_config(provider).get("models", {}).keys())

    def default_model(self, provider: str) -> str:
        """Return the default model for a provider."""
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
        # Pass through unknown names directly (e.g. newly released models not yet in config)
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

    def _get_client(self, provider: str, prov_cfg: dict):
        if provider not in self._provider_cache:
            api_key = self._get_api_key(provider, prov_cfg)
            ptype = prov_cfg.get("type", "openai_compatible")
            if ptype == "anthropic":
                self._provider_cache[provider] = _AnthropicProvider(api_key)
            else:
                base_url = prov_cfg.get("base_url")
                self._provider_cache[provider] = _OpenAIProvider(api_key, base_url)
        return self._provider_cache[provider]


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


def strip_think_stream(chunks: Iterator[str]) -> Iterator[str]:
    """Remove <think>...</think> reasoning blocks from a streaming response.

    Useful with reasoning models (DeepSeek-R1, Kimi-K2.5) that output
    chain-of-thought wrapped in <think> tags before the final answer.
    """
    OPEN, CLOSE = "<think>", "</think>"
    buf, in_think = "", False
    for chunk in chunks:
        buf += chunk
        out = ""
        while True:
            if in_think:
                idx = buf.find(CLOSE)
                if idx == -1:
                    buf = buf[-(len(CLOSE) - 1):] if len(buf) >= len(CLOSE) else buf
                    break
                buf = buf[idx + len(CLOSE):].lstrip("\n")
                in_think = False
            else:
                idx = buf.find(OPEN)
                if idx == -1:
                    tail = len(OPEN) - 1
                    if len(buf) > tail:
                        out += buf[:-tail]
                        buf = buf[-tail:]
                    break
                out += buf[:idx]
                buf = buf[idx + len(OPEN):]
                in_think = True
        if out:
            yield out
    if buf and not in_think:
        yield buf
