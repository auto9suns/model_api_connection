"""
Fetch & display models from all configured providers.

All runs show: Model ID · Age · $/1M (in/out) · Ctx · Flags · Description
  Flags: V=vision  F=tools  R=reasoning  C=cache  S=schema

Usage:
    python fetch_models.py                        # all providers, models released in last 6 months
    python fetch_models.py --all                  # every model regardless of age
    python fetch_models.py --current              # only models listed in models_config.json
    python fetch_models.py --provider openai
    python fetch_models.py --provider openai --all
    python fetch_models.py --current --provider anthropic
    python fetch_models.py --months 3             # change recency window

SiliconFlow prices scraped from siliconflow.cn/pricing (CNY per 1M tokens).
LiteLLM covers OpenAI / Anthropic / Gemini pricing (USD per 1M tokens).
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).parent))

CONFIG_PATH = Path(__file__).parent / "models_config.json"

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
    # YYYYMMDD anywhere, e.g. claude-haiku-4-5-20251001
    m = re.search(r'(\d{4})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])(?:\D|$)', model_id)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        except ValueError:
            pass
    # preview-MM-DD, e.g. gemini-2.5-flash-preview-04-17
    m = re.search(r'preview-(\d{2})-(\d{2})', model_id)
    if m:
        try:
            now = datetime.now(tz=timezone.utc)
            dt  = datetime(now.year, int(m.group(1)), int(m.group(2)), tzinfo=timezone.utc)
            return dt.replace(year=now.year - 1) if dt > now else dt
        except ValueError:
            pass
    return None


def _age_str(created: datetime | None, now: datetime) -> str:
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
    """display_name (if ≠ id) → LiteLLM mode → Gemini description snippet."""
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
    Returns {"_error": msg} on failure.
    """
    import urllib.request

    try:
        req = urllib.request.Request(
            "https://siliconflow.cn/pricing",
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
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
        with urllib.request.urlopen(url, timeout=10) as resp:
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


# ── Printer ────────────────────────────────────────────────────────────────────

def is_recent(created: datetime | None, cutoff: datetime) -> bool:
    return True if created is None else created >= cutoff


def print_provider_models(
    provider:   str,
    models:     list[dict],
    cutoff:     datetime,
    show_all:   bool,
    costs:      dict,
    sf_pricing: dict,
):
    now   = datetime.now(tz=timezone.utc)
    ID_W  = 50
    AGE_W = 12
    PRC_W = 15
    CTX_W = 5

    print(f"  {DIM}V=vision F=tools R=reasoning C=cache S=schema{RESET}")
    print(f"  {GRAY}{'Model ID':<{ID_W}}  {'Age':<{AGE_W}}  "
          f"{'$/1M in/out':<{PRC_W}}  {'Ctx':<{CTX_W}}  {'Flags':<11}  Description{RESET}")
    print("  " + "─" * (ID_W + AGE_W + PRC_W + CTX_W + 45))

    displayed = 0
    for m in models:
        recent = is_recent(m["created"], cutoff)
        if not show_all and not recent:
            continue

        age      = _age_str(m["created"], now)
        color    = GREEN if recent and m["created"] else (YELLOW if not m["created"] else GRAY)
        marker   = " ◆" if recent and m["created"] else ""
        lm_entry = get_litellm_entry(m["id"], provider, costs)
        desc     = get_desc(m, lm_entry)

        # Pricing
        if provider == "siliconflow":
            sf  = sf_pricing.get(m["id"])
            prc = fmt_price_cny(sf) if sf else "—"
        else:
            prc = fmt_price_usd(lm_entry) if lm_entry else "—"

        ctx   = fmt_ctx(lm_entry.get("max_input_tokens")) if lm_entry else "—"
        flags = fmt_flags(lm_entry) if lm_entry else f"{DIM}? ? ? ? ?{RESET}"

        print(f"  {color}{m['id']:<{ID_W}}{RESET}  "
              f"{GRAY}{age:<{AGE_W}}{RESET}  "
              f"{CYAN}{prc:<{PRC_W}}{RESET}  "
              f"{GRAY}{ctx:<{CTX_W}}{RESET}  "
              f"{flags:<11}  "
              f"{GRAY}{desc}{RESET}{marker}")
        displayed += 1

    if displayed == 0:
        print(f"  {GRAY}(no models in window — run with --all to see everything){RESET}")
    return displayed


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Fetch model lists from all LLM providers.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--provider", help="Limit to one provider (openai / anthropic / gemini / siliconflow)")
    parser.add_argument("--all",     dest="show_all", action="store_true",
                        help="Show all models, not just recent ones")
    parser.add_argument("--current", action="store_true",
                        help="Filter to only models listed in models_config.json")
    parser.add_argument("--months",  type=int, default=6,
                        help="Recency window in months (default: 6)")
    args = parser.parse_args()

    with open(CONFIG_PATH) as f:
        config = json.load(f)

    providers = config["providers"]
    if args.provider:
        if args.provider not in providers:
            print(f"Unknown provider '{args.provider}'. Available: {', '.join(providers)}")
            sys.exit(1)
        providers = {args.provider: providers[args.provider]}

    # Always load pricing
    costs = load_litellm_costs()

    sf_pricing: dict = {}
    if "siliconflow" in providers:
        print(f"{GRAY}Fetching SiliconFlow pricing from siliconflow.cn/pricing...{RESET}")
        sf_pricing = fetch_siliconflow_pricing()
        if "_error" in sf_pricing:
            print(f"{YELLOW}[warn] SiliconFlow pricing: {sf_pricing['_error']}{RESET}")
            sf_pricing = {}

    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=args.months * 30)

    scope = "config models only" if args.current else "all models"
    age_w = "all ages" if args.show_all else f"last {args.months} months"
    print(f"\n{BOLD}Fetching {scope}  ·  {age_w}  (◆ = within {args.months}mo){RESET}\n")

    for provider, prov_cfg in providers.items():
        print(f"{BOLD}[{provider}]{RESET}")
        result = fetch_provider(provider, prov_cfg)

        if isinstance(result, str):
            print(f"  {YELLOW}{result}{RESET}\n")
            continue

        # --current: keep only model IDs defined in config
        if args.current:
            config_ids = set(prov_cfg.get("models", {}).values())
            result = [m for m in result if m["id"] in config_ids]
            if not result:
                print(f"  {GRAY}(none of the config models were returned by the API){RESET}\n")
                continue

        count = print_provider_models(provider, result, cutoff, args.show_all, costs, sf_pricing)
        total = len(result)
        note  = " (config models)" if args.current else ""
        summary = f"  → {count} shown{note}" if args.show_all else f"  → {count} recent / {total} total{note}"
        print(f"{GRAY}{summary}{RESET}\n")


if __name__ == "__main__":
    main()
