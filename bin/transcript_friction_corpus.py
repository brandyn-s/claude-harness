#!/usr/bin/env python3
"""transcript_friction_corpus.py — mega-distill corpus-mode Phase A driver (friction spine).

Runs the deterministic friction spine over a whole cohort of transcripts IN-PROCESS (the extractor
is a pure-Python single-pass stream — far cheaper to loop here than to fan out 1200 subagents). For
each transcript it calls transcript_friction.extract(), writes a per-session friction record, and
accumulates them; then it runs the recurrence aggregation. The per-session records are written to
disk so the gate (transcript_friction_gate.py) can verify completeness/grounding against the cohort.

This is the FULL-CORPUS layer — cheap and deterministic, no token cost, no bound. The expensive
semantic layer (Phase B) is bounded separately.

Usage:
  python3 transcript_friction_corpus.py --cohort cohort.txt --out-dir <dir> [--min-breadth 2]
  (cohort.txt = one transcript path per line)
Emits: <out-dir>/records.jsonl (one friction record/session) + <out-dir>/friction_recurrence.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import transcript_friction as tf          # noqa: E402
import transcript_recurrence as tr        # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cohort", required=True, help="file of transcript paths, one per line")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--min-breadth", type=int, default=2)
    ap.add_argument("--examples", type=int, default=2)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    with open(args.cohort, encoding="utf-8") as fh:
        paths = [ln.strip() for ln in fh if ln.strip()]

    records = []
    records_path = os.path.join(args.out_dir, "records.jsonl")
    n_ok = n_skip = 0
    with open(records_path, "w", encoding="utf-8") as out:
        for p in paths:
            if not os.path.isfile(p):
                n_skip += 1
                continue
            try:
                rec = tf.extract(p, args.examples)
            except Exception as e:                       # never let one bad file abort the corpus
                n_skip += 1
                print(f"  skip (extract error) {os.path.basename(p)}: {e}", file=sys.stderr)
                continue
            out.write(json.dumps(rec) + "\n")
            records.append(rec)
            n_ok += 1

    result = tr.aggregate(records, args.min_breadth)
    rec_path = os.path.join(args.out_dir, "friction_recurrence.json")
    with open(rec_path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)

    print(f"mapped {n_ok} sessions ({n_skip} skipped/missing) of {len(paths)} cohort entries")
    print(f"sessions with >=1 friction event: {result['corpus_sessions']}")
    print(f"total friction events: {result['total_events']:,}")
    print(f"distinct signatures: {result['distinct_signatures']}  "
          f">= {args.min_breadth} sessions: {result['clusters_at_min_breadth']}")
    print("\ntop 30 cross-session recurring frictions (by breadth):")
    print(f"  {'breadth':>9}  {'%':>6}  {'total':>6}  signature")
    for c in result["clusters"][:30]:
        print(f"  {c['breadth']:>4}/{result['corpus_sessions']:<4} {c['breadth_pct']:>5.1f}%  "
              f"{c['total']:>6}  {c['signature']}")
    print(f"\nper-session records: {records_path}")
    print(f"recurrence table:    {rec_path}")


if __name__ == "__main__":
    main()
