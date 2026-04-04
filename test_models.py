"""
LLM API & Model Test Suite
===========================
Tests every configured provider and model by sending a minimal prompt.

Usage:
    python test_models.py                        # test all providers, default model only
    python test_models.py --all                  # test every model in config
    python test_models.py --provider openai      # test one provider (default model)
    python test_models.py --provider openai --all  # test all models of one provider
    python test_models.py --provider siliconflow --model deepseek-ai/DeepSeek-V3
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

# Allow running from any directory
sys.path.insert(0, str(Path(__file__).parent))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from model_connector import LLMConnector

PROBE = "Reply with exactly one word: OK"

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def test_model(llm: LLMConnector, provider: str, model: str) -> tuple[bool, str, float]:
    """
    Returns (success, message, elapsed_seconds).
    """
    try:
        t0 = time.monotonic()
        response = llm.chat(PROBE, provider=provider, model=model, max_tokens=16)
        elapsed = time.monotonic() - t0
        snippet = (response or "").strip().replace("\n", " ")[:60]
        return True, snippet, elapsed
    except EnvironmentError as e:
        return False, f"[NO API KEY] {e}", 0.0
    except Exception as e:
        return False, f"[ERROR] {type(e).__name__}: {e}", 0.0


def run_tests(providers_filter: str | None, models_filter: str | None, test_all: bool):
    llm = LLMConnector()

    providers = [providers_filter] if providers_filter else llm.list_providers()

    total = passed = failed = skipped = 0
    results: list[tuple[str, str, bool, str, float]] = []

    for provider in providers:
        try:
            all_models = llm.list_models(provider)
            default = llm.default_model(provider)
        except ValueError as e:
            print(f"{RED}✗ {provider}: {e}{RESET}")
            continue

        if models_filter:
            models_to_test = [models_filter]
        elif test_all:
            models_to_test = all_models
        else:
            models_to_test = [default]

        for model in models_to_test:
            total += 1
            ok, msg, elapsed = test_model(llm, provider, model)
            results.append((provider, model, ok, msg, elapsed))

            if ok:
                passed += 1
            elif "[NO API KEY]" in msg:
                skipped += 1
            else:
                failed += 1

    # ── Print results ──────────────────────────────────────────────────────────
    print()
    print(f"{BOLD}{'Provider':<14} {'Model':<46} {'Status':<8} {'Time':>6}  Response{RESET}")
    print("─" * 110)

    current_provider = None
    for provider, model, ok, msg, elapsed in results:
        if provider != current_provider:
            current_provider = provider
            print()

        if ok:
            status = f"{GREEN}✓ PASS{RESET}"
            time_str = f"{elapsed:.2f}s"
        elif "[NO API KEY]" in msg:
            status = f"{YELLOW}⚠ SKIP{RESET}"
            time_str = "  —"
        else:
            status = f"{RED}✗ FAIL{RESET}"
            time_str = "  —"

        print(f"  {provider:<12} {model:<46} {status}  {time_str:>6}  {msg}")

    # ── Summary ────────────────────────────────────────────────────────────────
    print()
    print("─" * 110)
    summary_parts = [f"Total: {total}", f"{GREEN}Passed: {passed}{RESET}"]
    if failed:
        summary_parts.append(f"{RED}Failed: {failed}{RESET}")
    if skipped:
        summary_parts.append(f"{YELLOW}Skipped (no key): {skipped}{RESET}")
    print("  " + "  |  ".join(summary_parts))
    print()

    return failed == 0


def main():
    parser = argparse.ArgumentParser(description="Test LLM API connectivity and model availability.")
    parser.add_argument("--provider", help="Test a specific provider only (e.g. openai, anthropic)")
    parser.add_argument("--model", help="Test a specific model only (must also specify --provider)")
    parser.add_argument("--all", dest="test_all", action="store_true",
                        help="Test every model in config (default: only the default model per provider)")
    args = parser.parse_args()

    if args.model and not args.provider:
        parser.error("--model requires --provider")

    ok = run_tests(
        providers_filter=args.provider,
        models_filter=args.model,
        test_all=args.test_all,
    )

    # Close the asyncio event loop created internally by litellm/httpx to
    # suppress the "Invalid file descriptor: -1" cleanup error on exit.
    try:
        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            loop.close()
    except Exception:  # nosec B110
        pass

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
