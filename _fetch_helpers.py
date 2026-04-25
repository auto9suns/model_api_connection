"""
Helpers for fetch_models.py — provider fetchers, pricing, and formatting.
"""

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "model_connector" / "models_config.json"

GREEN  = "\033[92m"
YELLOW = "\033[93m"
GRAY   = "\033[90m"
BOLD   = "\033[1m"
RESET  = "\033[0m"
CYAN   = "\033[96m"
DIM    = "\033[2m"


# ── Age helpers ────────────────────────────────────────────────────────────────

def extract_date_from_name(model_id: str) -> datetime | None:
    """Best-effort date extraction from model name as age fallback."""
    m = re.search(r'(\d{4})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?:\D|$)', model_id)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        except ValueError:
            pass
    m = re.search(r'preview-(\d{2})-(\d{2})', model_id)
    if m:
        try:
            now = datetime.now(tz=timezone.utc)
            dt  = datetime(now.year, int(m.group(1)), int(m.group(2)), tzinfo=timezone.utc)
            return dt.replace(year=now.year - 1) if dt > now else dt
        except ValueError:
            pass
    return None


def age_str(created: datetime | None, now: datetime) -> str:
    if not created:
        return "unknown"
    days = (now - created).days
    if days < 30:   return f"{days}d ago"
    if days < 365:  return f"{days // 30}mo ago"
    return f"{days // 365}y {days % 365 // 30}mo ago"


# ── LiteLLM helpers ────────────────────────────────────────────────────────────

LITELLM_PREFIX = {
    "openai":      "",
    "anthropic":   "",
    "gemini":      "gemini/",
    "siliconflow": "siliconflow/",
}


def load_litellm_costs() -> dict:
    try:
        import litellm
        return litellm.model_cost
    except ImportError:
        print(f"{YELLOW}[warn] litellm not installed — run: pip install litellm{RESET}")
        return {}
    except Exception as e:
        print(f"{YELLOW}[warn] litellm error: {e}{RESET}")
        return {}


def get_litellm_entry(model_id: str, provider: str, costs: dict) -> dict | None:
    prefix = LITELLM_PREFIX.get(provider, "")
    for key in (f"{prefix}{model_id}", model_id):
        if key in costs:
            return costs[key]
    return None


def fmt_price_usd(entry: dict) -> str:
    inp = (entry.get("input_cost_per_token")  or 0) * 1_000_000
    out = (entry.get("output_cost_per_token") or 0) * 1_000_000
    if inp == 0 and out == 0:
        return "—"
    return f"${inp:.2f}/${out:.2f}"


def fmt_ctx(tokens: int | None) -> str:
    if not tokens:
        return "—"
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:g}M"
    return f"{tokens // 1000}K"


def fmt_flags(entry: dict) -> str:
    checks = [
        ("V", entry.get("supports_vision")),
        ("F", entry.get("supports_function_calling") or entry.get("supports_parallel_function_calling")),
        ("R", entry.get("supports_reasoning")),
        ("C", entry.get("supports_prompt_caching")),
        ("S", entry.get("supports_response_schema")),
    ]
    return " ".join(label if val else f"{DIM}.{RESET}" for label, val in checks)


def get_desc(m: dict, lm_entry: dict | None, max_len: int = 26) -> str:
    display = m.get("display_name", "")
    if display and display != m["id"]:
        s = display
    elif lm_entry and lm_entry.get("mode"):
        s = f"[{lm_entry['mode']}]"
    elif m.get("description"):
        s = m["description"]
    else:
        return ""
    return s[:max_len] + ("…" if len(s) > max_len else "")


# ── SiliconFlow pricing scraper ────────────────────────────────────────────────

def fetch_siliconflow_pricing() -> dict[str, dict]:
    """
    Scrape https://siliconflow.cn/pricing (Next.js RSC stream).
    Returns {model_name: {"input_cny": float, "output_cny": float}}.
    """
    import urllib.request

    try:
        req = urllib.request.Request(
            "https://siliconflow.cn/pricing",
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:  # nosec # nosemgrep
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"_error": f"fetch failed: {e}"}

    raw_chunks = re.findall(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)', html)
    full_text = ""
    for chunk in raw_chunks:
        try:
            full_text += json.loads(f'"{chunk}"')
        except Exception:
            full_text += chunk
    if not full_text:
        full_text = html

    pricing: dict[str, dict] = {}
    for seg in re.split(r'"modelName"', full_text)[1:]:
        name_m = re.match(r'\s*:\s*"([^"]+)"', seg)
        if not name_m:
            continue
        model_name = name_m.group(1)
        window     = seg[:600]
        input_m    = re.search(r'"inputPrice"\s*:\s*"([^"]*)"',           window)
        output_m   = re.search(r'"(?:outputPrice|price)"\s*:\s*"([^"]*)"', window)
        if not input_m and not output_m:
            continue
        try:
            pricing[model_name] = {
                "input_cny":  float(input_m.group(1))  if input_m  and input_m.group(1)  else 0.0,
                "output_cny": float(output_m.group(1)) if output_m and output_m.group(1) else 0.0,
            }
        except ValueError:
            continue

    return pricing or {"_error": "no pricing data found (page structure may have changed)"}


def fmt_price_cny(entry: dict) -> str:
    inp, out = entry.get("input_cny", 0), entry.get("output_cny", 0)
    return "free" if inp == 0 and out == 0 else f"¥{inp:g}/¥{out:g}"


# ── Per-provider fetchers ──────────────────────────────────────────────────────

def _fetch_openai(api_key: str, base_url: str | None = None) -> list[dict]:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, **({"base_url": base_url} if base_url else {}))
    result = []
    for m in client.models.list():
        ts      = getattr(m, "created", None)
        created = datetime.fromtimestamp(ts, tz=timezone.utc) if ts and ts > 0 else None
        if not created:
            created = extract_date_from_name(m.id)
        result.append({"id": m.id, "created": created,
                        "owned_by": getattr(m, "owned_by", ""),
                        "display_name": "", "description": ""})
    return sorted(result, key=lambda x: x["created"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)


def _fetch_anthropic(api_key: str) -> list[dict]:
    from anthropic import Anthropic
    client = Anthropic(api_key=api_key)
    result = []
    for m in client.models.list().data:
        created = None
        raw = getattr(m, "created_at", None)
        if raw:
            if isinstance(raw, datetime):
                created = raw.replace(tzinfo=timezone.utc) if raw.tzinfo is None else raw
            elif isinstance(raw, str):
                created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if not created:
            created = extract_date_from_name(m.id)
        result.append({"id": m.id, "created": created,
                        "display_name": getattr(m, "display_name", ""), "description": ""})
    return sorted(result, key=lambda x: x["created"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)


def _fetch_gemini_native(api_key: str) -> list[dict]:
    import urllib.request
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}&pageSize=100"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # nosec # nosemgrep
            data = json.loads(resp.read())
        result = []
        for m in data.get("models", []):
            model_id = m.get("name", "").replace("models/", "")
            created  = extract_date_from_name(model_id)
            result.append({
                "id":           model_id,
                "created":      created,
                "display_name": m.get("displayName", ""),
                "description":  m.get("description", ""),
            })
        return sorted(result, key=lambda x: x["created"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    except Exception:
        return _fetch_openai(api_key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/")


def fetch_provider(provider: str, prov_cfg: dict) -> list[dict] | str:
    env_var = prov_cfg.get("api_key_env", "")
    api_key = os.environ.get(env_var, "")
    if not api_key:
        return f"[SKIP] {env_var} not set"
    try:
        ptype    = prov_cfg.get("type")
        base_url = prov_cfg.get("base_url")
        if ptype == "anthropic":
            return _fetch_anthropic(api_key)
        elif provider == "gemini":
            return _fetch_gemini_native(api_key)
        else:
            return _fetch_openai(api_key, base_url)
    except Exception as e:
        return f"[ERROR] {type(e).__name__}: {e}"
