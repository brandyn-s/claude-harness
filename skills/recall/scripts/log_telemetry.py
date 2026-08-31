"""Append one /recall telemetry record to ~/.claude/recall-telemetry.jsonl.

Telemetry phase + slot-use extension instrumented per the
memory-search-recall improvement workstream. The slot-use field
empirically resolves the pooled-judged-P@5-vs-telemetry tradeoff:
if >=70% of /recall invocations use only top-1/2 slots, pooled
judgment retires permanently; if usage spreads to slots 3-5,
multi-label precision matters and pooled judgment becomes worth
instrumenting.

Captures (per record):
- timestamp, query
- file_first_hit, file_first_path  (Step 2 outcome)
- fallback_used, top1_cosine       (Step 3 outcome)
- slots_used                       (Step 5 Pass 2 outcome — list[int],
                                    1-indexed slot numbers the consumer
                                    actually read for deep content)
- num_results                      (how many results the engine returned)

Usage (from inside the /recall skill, at the end of the flow):

  python3 ~/.claude/skills/recall/scripts/log_telemetry.py \
      --query "OBO authentication" \
      --file-first-hit true \
      --file-first-path topics/obo-authentication.md \
      --fallback-used false \
      --top1-cosine 0.0 \
      --slots-used "1,2" \
      --num-results 3

Booleans accept: true / false (case-insensitive).
top1-cosine accepts a float; pass 0.0 or omit if no engine call ran.
file-first-path may be empty when no file match was found.
slots-used accepts comma-separated 1-indexed slot numbers (e.g. "1,3");
pass "" or omit if no slots were read for deep content (e.g. no-results
or user-aborted).
num-results: total ranked items the engine returned (1..K). Captured
for future normalization of slot-use distribution against available
results count — analyze_telemetry.py does NOT yet read this field. The
field is logged so historical data is available once the analyzer is
extended; until then this is forward-looking instrumentation only.
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

LOG_PATH = Path.home() / ".claude" / "recall-telemetry.jsonl"


def _parse_bool(s: str) -> bool:
    return str(s).strip().lower() in {"true", "1", "yes", "y"}


def _parse_slots(s: str) -> list[int]:
    """Parse comma-separated 1-indexed slot numbers; empty -> []."""
    s = (s or "").strip()
    if not s:
        return []
    out: list[int] = []
    for tok in s.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            n = int(tok)
        except ValueError:
            continue
        if n >= 1:
            out.append(n)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Append a /recall telemetry record.")
    p.add_argument("--query", required=True)
    p.add_argument("--file-first-hit", required=True)
    p.add_argument("--file-first-path", default="")
    p.add_argument("--fallback-used", required=True)
    p.add_argument("--top1-cosine", type=float, default=0.0)
    p.add_argument("--slots-used", default="",
                   help="Comma-separated 1-indexed slot numbers the consumer "
                        "actually deep-read (e.g. '1,3'). Empty = none.")
    p.add_argument("--num-results", type=int, default=0,
                   help="Total ranked items the engine returned (0 if no engine call).")
    args = p.parse_args()

    slots = _parse_slots(args.slots_used)
    record = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "query": args.query,
        "file_first_hit": _parse_bool(args.file_first_hit),
        "file_first_path": args.file_first_path or None,
        "fallback_used": _parse_bool(args.fallback_used),
        # Preserve the literal value the caller passed (per SKILL.md
        # Step 7 field rules: "else 0.0" / "else 0"). The analyzer's
        # falsy filter treats 0.0 and null equivalently, so this change
        # is backwards-compatible with any pre-existing null records.
        "top1_cosine": args.top1_cosine,
        "slots_used": slots,
        "num_results": args.num_results,
    }

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    print(f"telemetry: {LOG_PATH.name} +1 record (slots={slots})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
