#!/usr/bin/env python3
"""Summarize ~/.claude/recall-telemetry.jsonl to resolve roundtable D2.

The roundtable's open D2 finding (META_SYNTHESIS 2026-05-17) was:
"pooled-judged P@5 vs unnecessary overhead — RESOLVABLE BY TELEMETRY.
If >=70% of /recall calls use only top-1/2, pooled judgment retires
permanently. If usage spreads to slots 3-5, multi-label precision
matters."

This script reads the telemetry JSONL and prints the empirical answer.
Run it after ~100-200 /recall invocations have accumulated.

Usage:
  python3 ~/.claude/skills/recall/scripts/analyze_telemetry.py
  python3 ~/.claude/skills/recall/scripts/analyze_telemetry.py --since 2026-05-18
"""

import argparse
import datetime
import json
import sys
from collections import Counter
from pathlib import Path

LOG_PATH = Path.home() / ".claude" / "recall-telemetry.jsonl"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--since", default="", help="ISO date or datetime; ignore records before this")
    p.add_argument("--path", default=str(LOG_PATH))
    args = p.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"No telemetry file at {path}", file=sys.stderr)
        return 1

    since_dt = None
    if args.since:
        try:
            since_dt = datetime.datetime.fromisoformat(args.since)
            if since_dt.tzinfo is None:
                since_dt = since_dt.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            print(f"--since must be ISO format; got {args.since!r}", file=sys.stderr)
            return 2

    records = []
    skipped = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if since_dt is not None:
                try:
                    ts = datetime.datetime.fromisoformat(rec["timestamp"])
                except (KeyError, ValueError):
                    continue
                # Backfill UTC on naive timestamps (legacy records, or
                # hand-edited entries) so the comparison with the
                # already-aware since_dt doesn't TypeError.
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=datetime.timezone.utc)
                if ts < since_dt:
                    continue
            records.append(rec)

    n = len(records)
    print(f"=== /recall telemetry summary ({path.name}) ===")
    print(f"  records: {n}  (skipped malformed: {skipped})")
    if n == 0:
        return 0

    ff_hit = sum(1 for r in records if r.get("file_first_hit"))
    fb_used = sum(1 for r in records if r.get("fallback_used"))
    print(f"  file_first hit:  {ff_hit:>4} / {n}  ({100*ff_hit/n:.1f}%)")
    print(f"  fallback used:   {fb_used:>4} / {n}  ({100*fb_used/n:.1f}%)")

    # top1 cosine distribution. Type-guard mirrors the malformed-JSON
    # defense above: skip non-numeric values instead of crashing on :.3f.
    cosines = [r["top1_cosine"] for r in records
               if isinstance(r.get("top1_cosine"), (int, float)) and r["top1_cosine"]]
    if cosines:
        cosines.sort()
        p50 = cosines[len(cosines) // 2]
        p10 = cosines[len(cosines) // 10] if len(cosines) >= 10 else cosines[0]
        p90 = cosines[(9 * len(cosines)) // 10] if len(cosines) >= 10 else cosines[-1]
        print(f"  top1 cosine:     p10={p10:.3f}  p50={p50:.3f}  p90={p90:.3f}  (n={len(cosines)})")

    # Slot-use distribution — the D2 answer
    print()
    print("=== Slot-use distribution (Step 5 Pass 2 deep reads) ===")
    records_with_slots = [r for r in records if r.get("slots_used")]
    if not records_with_slots:
        print("  No records with slots_used yet. After /recall has run with the")
        print("  updated SKILL.md a few times, this section becomes meaningful.")
        return 0

    n_slot_records = len(records_with_slots)
    slot_freq: Counter[int] = Counter()
    max_slot_per_record = []
    only_top12 = 0
    for r in records_with_slots:
        raw = r.get("slots_used")
        # Same type-guard: drop non-int slot entries (and non-list shapes)
        # instead of crashing on max()/range() int comparisons.
        slots = [s for s in raw if isinstance(s, int)] if isinstance(raw, list) else []
        for s in slots:
            slot_freq[s] += 1
        if slots:
            max_slot_per_record.append(max(slots))
            if max(slots) <= 2:
                only_top12 += 1

    print(f"  records with deep reads: {n_slot_records}")
    print("  slot frequency:")
    max_slot = max(slot_freq) if slot_freq else 0
    for s in range(1, max_slot + 1):
        count = slot_freq.get(s, 0)
        bar = "#" * min(40, count)
        print(f"    slot {s:>2}: {count:>3} {bar}")

    pct_top12 = 100 * only_top12 / n_slot_records if n_slot_records else 0
    print()
    print("=== D2 verdict (per META_SYNTHESIS 2026-05-17) ===")
    print(f"  Records using ONLY slots 1-2 (max_slot <= 2): {only_top12} / {n_slot_records}  ({pct_top12:.1f}%)")
    print()
    if pct_top12 >= 70:
        print("  -> D2 RESOLVED toward GROK: pooled-judged P@5 RETIRES PERMANENTLY.")
        print("     The labeling budget is better spent on production-shape golden expansion.")
    elif pct_top12 >= 50:
        print("  -> D2 LEANING toward GROK but not decisive. Recommend gathering 100+ more records.")
    else:
        print("  -> D2 RESOLVED toward GPT/OPUS: slots 3-5 are exercised; multi-label precision matters.")
        print("     Pooled-judged P@5 is worth instrumenting as a sampled audit.")

    if n_slot_records < 50:
        print()
        print(f"  WARNING: sample size n={n_slot_records} is below 50. Treat verdict as preliminary;")
        print("  expand to >=100 deep-read records before locking the D2 decision.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
