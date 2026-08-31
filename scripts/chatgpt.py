"""Direct OpenAI Responses-API wrapper.

Reads OPENAI_API_KEY from env. Prints response on stdout, with a trailing
usage/cost line also on stdout. stderr is reserved for errors.

Targets POST /v1/responses (the modern endpoint OpenAI is migrating to).
Supports gpt-5.5, gpt-5.5-pro, gpt-5*, gpt-4o*, o-series, etc.

Out of scope: streaming, multi-turn (use previous_response_id manually
via -j JSON output), vision/audio, tools/function calling.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import requests

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

ENDPOINT = "https://api.openai.com/v1/responses"
TIMEOUT = 600  # gpt-5.5-pro at high/xhigh effort can take minutes on heavy reasoning.

# Pricing snapshot (USD per 1M tokens). Source: developers.openai.com.
# Unknown models fall through to "(unknown pricing)" in estimate_cost.
PRICING: dict[str, tuple[float, float]] = {
    # GPT-5.5 family (released 2026-04-23).
    "gpt-5.5-pro":              (30.000, 180.000),
    "gpt-5.5-pro-2026-04-23":   (30.000, 180.000),
    "gpt-5.5":                  ( 5.000,  30.000),
    "gpt-5.5-2026-04-23":       ( 5.000,  30.000),
    # Older snapshot — verify at https://openai.com/api/pricing/.
    "gpt-4o-mini":              ( 0.150,   0.600),
    "gpt-4o":                   ( 2.500,  10.000),
    "gpt-4o-2024-08-06":        ( 2.500,  10.000),
    "gpt-4-turbo":              (10.000,  30.000),
    "o1":                       (15.000,  60.000),
    "o1-mini":                  ( 3.000,  12.000),
    "o3-mini":                  ( 1.100,   4.400),
}

# Per the OpenAPI spec (ReasoningEffort schema, 2026-05).
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")

# Models that accept the `reasoning` parameter on /v1/responses. Older chat
# models (gpt-4o*, gpt-4*, gpt-3.5*) reject it with HTTP 400.
REASONING_MODEL_PREFIXES = ("gpt-5.5", "gpt-5", "o1", "o3", "o4")

# Models that accept the full effort range including 'xhigh'. gpt-5 and
# o-series only accept none/minimal/low/medium/high.
XHIGH_CAPABLE_PREFIXES = ("gpt-5.5",)


def _accepts_reasoning(model: str) -> bool:
    return model.startswith(REASONING_MODEL_PREFIXES)


def _default_effort_for(model: str) -> str:
    """Per-model default when --effort isn't explicitly passed."""
    if model.startswith(XHIGH_CAPABLE_PREFIXES):
        return "xhigh"
    return "high"


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> str:
    """Cost from input + output tokens (output includes reasoning tokens)."""
    if model not in PRICING:
        return "(unknown pricing)"
    in_rate, out_rate = PRICING[model]
    cost = (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000
    return f"${cost:.6f}"


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="chatgpt",
        description="One-shot OpenAI Responses-API wrapper.",
    )
    p.add_argument("prompt", nargs="?", help="Prompt text. If omitted, read from stdin.")
    p.add_argument("-m", "--model", default="gpt-5.5", help="Model id (default: gpt-5.5).")
    p.add_argument("-s", "--system", default=None, help="System prompt (sent as `instructions`).")
    p.add_argument("-t", "--temperature", type=float, default=None,
                   help="Sampling temperature (not supported by all models).")
    p.add_argument("-x", "--max-tokens", type=int, default=None, dest="max_tokens",
                   help="Output cap. Mapped to max_output_tokens.")
    p.add_argument("-e", "--effort", choices=REASONING_EFFORTS, default=None,
                   help="reasoning effort. Auto-defaults to 'xhigh' for gpt-5.5*, "
                        "'high' for other reasoning models, omitted for non-reasoning models.")
    p.add_argument("--seed", type=int, default=None,
                   help="(Deprecated) seed is not supported by /v1/responses; flag is ignored with a warning.")
    p.add_argument("-j", "--json", action="store_true", help="Print raw API JSON to stdout.")
    return p.parse_args(argv)


def build_payload(prompt: str, args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": args.model, "input": prompt}
    if args.system:
        payload["instructions"] = args.system
    if args.temperature is not None:
        # Reasoning models (gpt-5.5*, gpt-5*, o-series) reject temperature.
        if _accepts_reasoning(args.model):
            sys.stderr.write(
                f"warning: model '{args.model}' does not accept temperature; "
                f"dropping -t {args.temperature}\n"
            )
        else:
            payload["temperature"] = args.temperature
    if args.max_tokens is not None:
        payload["max_output_tokens"] = args.max_tokens
    if _accepts_reasoning(args.model):
        effort = args.effort if args.effort is not None else _default_effort_for(args.model)
        payload["reasoning"] = {"effort": effort}
    elif args.effort is not None:
        sys.stderr.write(
            f"warning: model '{args.model}' does not accept reasoning_effort; dropping -e {args.effort}\n"
        )
    if args.seed is not None:
        sys.stderr.write(
            f"warning: --seed is not supported by /v1/responses; dropping --seed {args.seed}\n"
        )
    return payload


def extract_text(data: dict[str, Any]) -> str:
    """Find the assistant message's output_text in a Responses-API response.

    The output array can contain reasoning items, tool-call items, and message
    items. Only message items have user-visible text content.
    """
    for item in data.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return content.get("text", "")
    return ""


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt is not None:
        return args.prompt
    if sys.stdin.isatty():
        sys.stderr.write("error: no prompt provided (pass as arg or pipe stdin)\n")
        sys.exit(2)
    return sys.stdin.read()


def call_api(api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    r = requests.post(
        ENDPOINT,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=TIMEOUT,
    )
    if r.status_code == 401:
        sys.stderr.write("error: 401 unauthorized — check OPENAI_API_KEY\n")
        sys.exit(3)
    if r.status_code == 404:
        sys.stderr.write(f"error: 404 model not found — '{payload.get('model')}'\n")
        sys.exit(4)
    if r.status_code == 429:
        sys.stderr.write("error: 429 rate-limited — back off and retry\n")
        sys.exit(5)
    if not r.ok:
        sys.stderr.write(f"error: {r.status_code} — {r.text[:500]}\n")
        sys.exit(6)
    return r.json()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        sys.stderr.write("error: OPENAI_API_KEY not set\n")
        return 1
    prompt = read_prompt(args)
    payload = build_payload(prompt, args)
    data = call_api(api_key, payload)

    if args.json:
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return 0

    text = extract_text(data)
    status = data.get("status")
    incomplete = status == "incomplete" or not text
    if incomplete:
        reason = (data.get("incomplete_details") or {}).get("reason")
        rtoks = data.get("usage", {}).get("output_tokens_details", {}).get("reasoning_tokens")
        sys.stderr.write(
            f"warning: response status={status} (reason={reason}, "
            f"reasoning_tokens={rtoks}); output may be empty or truncated. "
            f"Raise -x/--max-tokens or lower -e/--effort "
            f"(e.g. -m gpt-5.5 -e low for simple tasks).\n"
        )
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")

    usage = data.get("usage", {})
    in_tokens = usage.get("input_tokens", 0)
    out_tokens = usage.get("output_tokens", 0)
    cost = estimate_cost(args.model, in_tokens, out_tokens)
    sys.stdout.write(f"[{args.model}] tokens: {in_tokens} in / {out_tokens} out — {cost}\n")
    return 7 if incomplete else 0


if __name__ == "__main__":
    sys.exit(main())
