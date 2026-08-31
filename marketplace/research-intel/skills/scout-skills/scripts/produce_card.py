"""Independent technique-card production for the 3rd-party validation.

Reads a community SKILL.md and asks GPT-5.5-pro to produce a Step 2.7
technique card using the same 4-field schema. The model has no prior
priming from my hand-authored cards.

Output is the raw model response — to be compared against my cards
post-hoc.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "roundtable" / "scripts"
sys.path.insert(0, str(ROOT))
from adapters import openai_adapter  # noqa: E402


PROMPT = """You are extracting a TECHNIQUE CARD from a community SKILL.md file. This is the Step 2.7 step from the /scout-skills workflow.

The technique card has FOUR required fields. Produce it in this exact format:

```
TECHNIQUE CARD: <one-line title>

Underlying technique:
  What is the operationalizable mechanism this skill encodes?
  Name it as a noun phrase that survives extraction from this SKILL.md.
  Examples of GOOD names: "per-interaction STRIDE threat-analysis methodology",
                          "characterisation-test placeholder-driven extraction algorithm",
                          "mutation-testing equivalent-mutant detection heuristic".
  Examples of BAD names: "STRIDE matrix", "characterisation tests", "mutation testing"
  (those are the visual artifact or the topic, not the technique).

Domain it serves:
  Threat modeling? Legacy code testing? Async error handling? Be specific.
  If you cannot name a domain narrower than "Claude Code skill writing",
  the candidate is likely architecture polish — flag it explicitly as such.

Operationalizable atom:
  What is the smallest unit a reader could USE? An algorithm with inputs/outputs,
  a heuristic with a stopping rule, a rubric with thresholds, a classification
  scheme with mutually-exclusive categories. If the atom is "use this layout"
  or "add this section", the pattern is editorial polish, not substance.

Source of the technique:
  Did the SKILL.md author import this from industry (TRIZ, FMEA, chaos
  engineering, property-based testing)? From research (a specific paper,
  methodology)? From production experience (cite the incident if named)?
  Or is it a Claude Code coordination pattern invented in the SKILL.md itself?
```

If the SKILL.md is purely editorial polish with no operationalizable atom (no
algorithm, no heuristic, no rubric, no classification scheme), produce the
card anyway but mark each field with "EDITORIAL-ONLY: <one-sentence reason>"
rather than fabricating substance that isn't there.

Be honest. Do not invent technique-substance that isn't in the SKILL.md.
Do not hedge. Pick the most concrete technique the SKILL.md actually encodes.

COMMUNITY SKILL.md:
```
{content}
```

Produce the technique card now. No preamble, no discussion — just the card."""


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--max-chars", type=int, default=20000)
    args = p.parse_args()

    if not args.input.exists():
        print(f"ERROR: {args.input} not found", file=sys.stderr)
        return 1

    content = args.input.read_text(encoding="utf-8", errors="replace")[: args.max_chars]
    prompt = PROMPT.format(content=content)

    start = time.time()
    result = openai_adapter.call(prompt, max_tokens=2000)
    elapsed = time.time() - start

    # Ensure the output parent dir exists. Without this, write_text
    # raises FileNotFoundError on the first run of a session because
    # /tmp/scout-skills/ does not exist yet.
    args.output.parent.mkdir(parents=True, exist_ok=True)

    if not result.get("ok"):
        msg = f"ERROR: {result.get('error', 'unknown')}"
        args.output.write_text(msg, encoding="utf-8")
        print(msg, file=sys.stderr)
        return 1

    args.output.write_text(result["text"], encoding="utf-8")
    print(f"OK: {args.input.name} -> {args.output} ({elapsed:.1f}s, "
          f"in={result.get('input_tokens', 0)}, out={result.get('output_tokens', 0)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
