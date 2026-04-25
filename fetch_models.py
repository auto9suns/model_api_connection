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
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from _fetch_helpers import (
    GREEN, YELLOW, GRAY, BOLD, RESET, CYAN, DIM,
    age_str, load_litellm_costs, get_litellm_entry,
    fmt_price_usd, fmt_price_cny, fmt_ctx, fmt_flags, get_desc,
    fetch_siliconflow_pricing, fetch_provider,
)

CONFIG_PATH = Path(__file__).parent / "model_connector" / "models_config.json"


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

        age      = age_str(m["created"], now)
        color    = GREEN if recent and m["created"] else (YELLOW if not m["created"] else GRAY)
        marker   = " ◆" if recent and m["created"] else ""
        lm_entry = get_litellm_entry(m["id"], provider, costs)
        desc     = get_desc(m, lm_entry)

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
