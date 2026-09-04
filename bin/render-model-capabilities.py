#!/usr/bin/env python3
"""Render contracts/model-capabilities.json into skills/api-guardrails/SKILL.md.

The per-model capability matrix used to be hand-written prose in the skill while
the same facts lived again as frozensets in scripts/validate-skills.py. The
contract is now the only place they are stated. This script renders the table
between the `<!-- model-capabilities:begin -->` / `<!-- model-capabilities:end -->`
markers, and bin/test_render_model_capabilities.py fails when the block in the
skill differs from the render, so the document cannot drift from the contract.

Usage:
    python3 bin/render-model-capabilities.py --check   # exit 1 if the block is stale
    python3 bin/render-model-capabilities.py --write   # rewrite the block in place
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "model-capabilities.json"
SKILL = ROOT / "skills" / "api-guardrails" / "SKILL.md"
BEGIN = "<!-- model-capabilities:begin -->"
END = "<!-- model-capabilities:end -->"

COLUMNS = ("Model", "Thinking", "Effort", "Request restrictions", "Retention and refusal notes")


def load_contract(path: Path = CONTRACT) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _code(items) -> str:
    return "/".join(f"`{item}`" for item in items)


def _thinking(model: dict, levels: list[str]) -> str:
    thinking = model["thinking"]
    disable = thinking["disable"]
    parts: list[str] = []
    adaptive = thinking["adaptive"]
    if adaptive == "always_on":
        parts.append('Adaptive thinking is always on; `thinking: {"type": "disabled"}` returns 400.')
    elif adaptive == "default_on":
        if not disable["allowed"]:
            parts.append('Adaptive thinking is on by default; `thinking: {"type": "disabled"}` returns 400.')
        elif disable["max_effort"]:
            cap = disable["max_effort"]
            above = levels[levels.index(cap) + 1:]
            parts.append(
                f"Adaptive thinking is on by default. Thinking may be disabled at `{levels[0]}` "
                f"through `{cap}`; disabled + {_code(above)} returns 400."
            )
        else:
            parts.append("Adaptive thinking is on by default and may be disabled at any supported effort.")
    elif adaptive == "default_off":
        parts.append("Adaptive thinking is available but off unless requested.")
    elif adaptive == "unsupported":
        parts.append("Adaptive thinking is not supported.")
    else:
        raise ValueError(f"{model['id']}: unknown thinking.adaptive {adaptive!r}")
    if thinking["manual_budget_tokens"]:
        parts.append("Manual extended thinking (`enabled` + `budget_tokens`) is supported.")
    else:
        parts.append("Manual `enabled`/`budget_tokens` returns 400.")
    return " ".join(parts)


def _effort(model: dict) -> str:
    effort = model["effort"]
    if not effort["levels"]:
        return "Effort is unavailable."
    return ", ".join(
        f"`{level}`" + (" (default)" if level == effort["default"] else "")
        for level in effort["levels"]
    )


def _restrictions(model: dict) -> str:
    sampling = {
        "rejected": "Non-default `temperature`/`top_p`/`top_k` return 400.",
        "temperature_or_top_p": "`temperature` or `top_p` may be set, one at a time.",
    }[model["sampling"]]
    prefill = (
        "Assistant-message prefill is accepted."
        if model["assistant_prefill"]
        else "Assistant-message prefill returns 400."
    )
    return f"{sampling} {prefill}"


def _thousands(tokens: int) -> str:
    return f"{tokens // 1000}k"


def _notes(model: dict) -> str:
    parts: list[str] = []
    if model["availability"] == "project-glasswing":
        parts.append("Limited Project Glasswing availability.")
    retention = model["retention"]
    if retention["covered_model"]:
        parts.append(
            f"Covered Model: requires {retention['minimum_days']}-day data retention "
            "and is unavailable under ZDR."
        )
    refusals = {
        "classifier": "Handle classifier refusals and qualify fallback behavior.",
        "cyber_safeguards": "Handle cyber-safeguard refusals.",
        "none": "It has no Fable safety classifiers.",
    }
    if model["refusals"]:
        parts.append(refusals[model["refusals"]])
    if model["web_fetch"] is True:
        parts.append("Web fetch is available.")
    elif model["web_fetch"] is False:
        parts.append("Web fetch is unavailable.")
    if model["priority_tier"] is True:
        parts.append("Priority Tier is supported.")
    elif model["priority_tier"] is False:
        parts.append("Priority Tier is unavailable.")
    if model["context_window_tokens"]:
        parts.append(
            f"{_thousands(model['context_window_tokens'])} context window; "
            f"up to {_thousands(model['max_output_tokens'])} output tokens."
        )
    parts.extend(model["notes"])
    return " ".join(parts)


def render_block(contract: dict) -> str:
    """The full marker-delimited block, newline-terminated."""
    levels = list(contract["effort_levels"])
    lines = [
        BEGIN,
        ("<!-- Generated from contracts/model-capabilities.json by "
         "bin/render-model-capabilities.py; edit the contract, then run it with --write. -->"),
        (f"Rows verified {contract['verified_on']} against the primary sources above; "
         "`contracts/model-capabilities.json` is the source of record."),
        "",
        "| " + " | ".join(COLUMNS) + " |",
        "|" + "---|" * len(COLUMNS),
    ]
    for model in contract["models"]:
        cells = (
            f"{model['display_name']} (`{model['id']}`)",
            _thinking(model, levels),
            _effort(model),
            _restrictions(model),
            _notes(model),
        )
        lines.append("| " + " | ".join(cells) + " |")
    lines.append(END)
    return "\n".join(lines) + "\n"


def current_block(text: str) -> str:
    """The marker-delimited block as it stands in the skill, newline-terminated."""
    start = text.find(BEGIN)
    end = text.find(END)
    if start < 0 or end < 0 or end < start:
        raise ValueError(f"{SKILL}: missing or misordered {BEGIN} / {END} markers")
    return text[start:end + len(END)] + "\n"


def splice(text: str, block: str) -> str:
    old = current_block(text)
    return text.replace(old, block, 1)


def _shown(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="exit 1 if the skill's block is stale")
    mode.add_argument("--write", action="store_true", help="rewrite the block in place")
    args = ap.parse_args(argv)

    block = render_block(load_contract())
    text = SKILL.read_text(encoding="utf-8")
    if args.check:
        if current_block(text) == block:
            print("model-capabilities block is current")
            return 0
        print(f"{_shown(SKILL)}: model-capabilities block is stale; run with --write", file=sys.stderr)
        return 1
    SKILL.write_text(splice(text, block), encoding="utf-8")
    print(f"wrote {_shown(SKILL)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
