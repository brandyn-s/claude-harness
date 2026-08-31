#!/usr/bin/env python3
"""Report the model Claude Code is ACTUALLY using, and why it may differ from config.

Configured is not effective. `settings.json`, the statusline, and the model's own
self-description can all name a model that is not the one serving the request.
The only oracle is a real request: `claude -p --output-format json` returns a
`modelUsage` map keyed by the model that actually ran, carrying its
`canonicalModel`, `provider`, `contextWindow` and `maxOutputTokens`.

Motivating failure (2026-08-29): a session opened with

    Switched to Opus 5 (1M context) because Fable 5 is not available

The cause was one poisoned string -- `settings.json` held
`"model": "us.anthropic.claude-fable-5"`, a BEDROCK inference-profile id, on a
first-party subscription that only accepts bare ids like `claude-fable-5[1m]`.
Nothing reported the fallback's reason; four separate reads of config, launcher
env, and the statusline all looked correct. One probe would have shown
`canonicalModel` disagreeing with the configured value immediately.

COST: this makes a real API request. The trivial prompt is cheap in output tokens
but the system prompt is not -- a measured run wrote 96,272 cache-creation
tokens for $2.12. Do not poll it, and do not put it in a hook or a loop.

Usage:
    python3 bin/effective-model.py            # human-readable
    python3 bin/effective-model.py --json     # machine-readable
    python3 bin/effective-model.py --timeout 300
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# A provider-prefixed id in a first-party session is the exact poison that
# caused the motivating failure: it is a valid Bedrock inference profile and an
# invalid first-party model name, so it fails only at request time.
PROVIDER_PREFIXES = (
    "us.anthropic.", "us-gov.anthropic.", "eu.anthropic.", "apac.anthropic.", "arn:aws",
)


def probe(timeout: int) -> dict:
    """Run the one authoritative request. Returns the parsed result envelope."""
    exe = shutil.which("claude")
    if not exe:
        raise SystemExit("claude CLI not found on PATH")
    proc = subprocess.run(
        [exe, "-p", "say ok", "--output-format", "json"],
        capture_output=True, text=True, timeout=timeout, check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"probe failed (exit {proc.returncode}): "
                         f"{(proc.stderr or proc.stdout)[:400]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"probe returned non-JSON: {proc.stdout[:300]}") from exc


def effective(env: dict) -> list[dict]:
    """Every model that actually served part of the request.

    Returned as a list, not a single value: a fallback or a subagent can make
    more than one model appear, and collapsing that to one would hide exactly
    the divergence this tool exists to surface.
    """
    out = []
    for key, usage in (env.get("modelUsage") or {}).items():
        out.append({
            "model": usage.get("canonicalModel") or key,
            "provider": usage.get("provider"),
            "context_window": usage.get("contextWindow"),
            "max_output_tokens": usage.get("maxOutputTokens"),
            "cost_usd": usage.get("costUSD"),
        })
    return out


def configured() -> dict:
    """What the readable config layers ASK for.

    Deliberately partial: managed/MDM policy outranks all of these and is not
    read here, so a divergence this tool cannot explain may be a managed
    override rather than a bug.
    """
    cfg: dict = {"settings_model": None, "settings_fallback": None, "env": {}}
    settings = Path.home() / ".claude" / "settings.json"
    if settings.exists():
        try:
            data = json.loads(settings.read_text(encoding="utf-8"))
            cfg["settings_model"] = data.get("model")
            cfg["settings_fallback"] = data.get("fallbackModel")
            for k, v in (data.get("env") or {}).items():
                if "MODEL" in k:
                    cfg["env"][f"settings.env.{k}"] = v
        except (OSError, json.JSONDecodeError) as exc:
            cfg["settings_error"] = str(exc)
    for k in ("ANTHROPIC_MODEL", "ANTHROPIC_SMALL_FAST_MODEL",
              "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
              "CLAUDE_CODE_SUBAGENT_MODEL"):
        if os.environ.get(k):
            cfg["env"]["$" + k] = os.environ[k]
    return cfg


def findings(eff: list[dict], cfg: dict) -> list[str]:
    """Problems worth naming, most actionable first."""
    notes = []
    first_party = any(m.get("provider") == "firstParty" for m in eff)
    candidates = {"model (settings.json)": cfg.get("settings_model")}
    fb = cfg.get("settings_fallback")
    for i, f in enumerate(fb if isinstance(fb, list) else [fb]):
        if f:
            candidates[f"fallbackModel[{i}]"] = f
    candidates.update(cfg.get("env") or {})

    for where, value in candidates.items():
        if isinstance(value, str) and value.startswith(PROVIDER_PREFIXES):
            verdict = ("INVALID on this first-party session" if first_party
                       else "provider-prefixed")
            notes.append(f"{where} = {value!r} is {verdict}. "
                         f"First-party ids are bare, e.g. 'claude-fable-5[1m]'.")

    names = {m["model"] for m in eff}
    want = cfg.get("settings_model")
    if isinstance(want, str) and names:
        stem = want.split("[")[0].split(".")[-1]
        if not any(stem in n for n in names):
            notes.append(f"configured {want!r} but {sorted(names)} served the "
                         f"request -- a silent fallback occurred.")

    for m in eff:
        cw = m.get("context_window")
        if isinstance(cw, int) and cw < 1_000_000:
            notes.append(f"{m['model']} has a {cw:,}-token window. If 1M was "
                         f"intended, the '[1m]' suffix is load-bearing and "
                         f"missing somewhere.")
    return notes


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--timeout", type=int, default=240,
                    help="seconds to wait for the probe (default 240)")
    args = ap.parse_args()

    env = probe(args.timeout)
    eff = effective(env)
    cfg = configured()
    notes = findings(eff, cfg)

    if args.json:
        print(json.dumps({"effective": eff, "configured": cfg, "findings": notes,
                          "probe_cost_usd": env.get("total_cost_usd"),
                          "fast_mode_state": env.get("fast_mode_state")}, indent=2))
        return 1 if notes else 0

    print("EFFECTIVE (from a real request -- the only oracle):")
    if not eff:
        print("  (probe returned no modelUsage; treat as UNKNOWN, not as absent)")
    for m in eff:
        cw = m["context_window"]
        mo = m["max_output_tokens"]
        print(f"  {m['model']}")
        print(f"    provider          {m['provider']}")
        print(f"    context window    {cw:,}" if isinstance(cw, int) else
              f"    context window    {cw}")
        print(f"    max output        {mo:,}" if isinstance(mo, int) else
              f"    max output        {mo}")

    print("\nCONFIGURED (readable layers only; managed policy outranks these):")
    print(f"  model                 {cfg.get('settings_model')!r}")
    print(f"  fallbackModel         {cfg.get('settings_fallback')!r}")
    for k, v in (cfg.get("env") or {}).items():
        print(f"  {k:21} {v!r}")

    print(f"\nfast mode: {env.get('fast_mode_state')}"
          f" ({env.get('fast_mode_disabled_reason') or 'n/a'})")
    print(f"probe cost: ${env.get('total_cost_usd', 0):.2f}"
          "  -- a real request; do not poll this")

    if notes:
        print("\nFINDINGS:")
        for n in notes:
            print(f"  - {n}")
        return 1
    print("\nNo divergence between the readable config and the served model.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
