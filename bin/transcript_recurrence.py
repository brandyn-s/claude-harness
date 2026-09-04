#!/usr/bin/env python3
"""transcript_recurrence.py — mega-distill corpus-mode Phase A2: cross-session recurrence reduce.

THE anti-census deliverable. Reads the per-session friction records emitted by
transcript_friction.py (one JSON object per line, the corpus map output) and aggregates them into a
BREADTH-RANKED table: for each friction signature, in how many DISTINCT sessions does it occur, and
how many times total. Ranked by BREADTH (session count), not raw frequency — because a pattern in
40/450 sessions is a systemic habit worth a rule, while 200 occurrences in one session is a single
bad day. Breadth is the signal a per-session distill structurally cannot see.

This is deterministic: it only counts and groups what the (deterministic) extractor emitted. No LLM,
no fabrication surface — every session id in every cluster traces to a real input record, which
transcript_friction_gate.py asserts.

Input : a JSONL file (one friction record per line) OR a directory of *.json friction records.
Output: friction_recurrence.json — {corpus_sessions, total_events, clusters:[{signature, breadth,
        sessions:[ids], total, mean_per_session, examples}]} ranked by breadth desc.

Usage:
  python3 transcript_recurrence.py --records <file.jsonl | dir> --out friction_recurrence.json
                                   [--min-breadth 2] [--top 0]
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _load_records(src):
    """Yield friction records from a JSONL file or a directory of *.json files."""
    if os.path.isdir(src):
        for fn in sorted(os.listdir(src)):
            if fn.endswith(".json"):
                with open(os.path.join(src, fn), encoding="utf-8") as fh:
                    try:
                        yield json.load(fh)
                    except Exception:  # noqa: S112, BLE001 -- report tooling: skip unreadable record files
                        continue  # skip unreadable record
    else:
        with open(src, encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    yield json.loads(raw)
                except Exception:  # noqa: S112, BLE001 -- report tooling: skip unparseable JSONL lines
                    continue  # skip unparseable line


def aggregate(records, min_breadth=2):
    """Aggregate per-session friction records into breadth-ranked signature clusters."""
    # signature -> {sessions:set, total:int, examples:list}
    agg = {}
    corpus_sessions = set()
    total_events = 0
    for rec in records:
        sid = rec.get("session")
        if not sid:
            continue
        corpus_sessions.add(sid)
        for sig, count in (rec.get("signatures") or {}).items():
            total_events += count
            a = agg.setdefault(sig, {"sessions": set(), "total": 0, "examples": []})
            a["sessions"].add(sid)
            a["total"] += count
            # carry a couple of examples from the first sessions that exhibit the signature
            if len(a["examples"]) < 3:
                for ex in (rec.get("examples") or {}).get(sig, [])[:1]:
                    a["examples"].append(ex)

    clusters = []
    for sig, a in agg.items():
        breadth = len(a["sessions"])
        if breadth < min_breadth:
            continue
        clusters.append({
            "signature": sig,
            "breadth": breadth,
            "breadth_pct": round(100.0 * breadth / max(1, len(corpus_sessions)), 1),
            "total": a["total"],
            "mean_per_session": round(a["total"] / breadth, 1),
            "sessions": sorted(a["sessions"]),
            "examples": a["examples"],
        })
    # Rank by breadth desc, then total desc as a tiebreak.
    clusters.sort(key=lambda c: (-c["breadth"], -c["total"]))
    return {
        "corpus_sessions": len(corpus_sessions),
        "total_events": total_events,
        "distinct_signatures": len(agg),
        "clusters_at_min_breadth": len(clusters),
        "min_breadth": min_breadth,
        "clusters": clusters,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", required=True, help="JSONL file or directory of friction records")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-breadth", type=int, default=2,
                    help="drop signatures occurring in fewer than N distinct sessions (default 2; a "
                         "single-session signature is not 'recurring across sessions')")
    ap.add_argument("--top", type=int, default=0, help="print top N clusters (0 = 25)")
    args = ap.parse_args()

    records = list(_load_records(args.records))
    if not records:
        print("no friction records found", file=sys.stderr)
        sys.exit(2)
    result = aggregate(records, args.min_breadth)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)

    top = args.top or 25
    print(f"corpus sessions with friction: {result['corpus_sessions']}")
    print(f"total friction events: {result['total_events']:,}")
    print(f"distinct signatures: {result['distinct_signatures']}  "
          f"(>= {args.min_breadth} sessions: {result['clusters_at_min_breadth']})")
    print(f"\ntop {top} cross-session recurring frictions (by breadth):")
    print(f"  {'breadth':>8}  {'%corpus':>7}  {'total':>6}  signature")
    for c in result["clusters"][:top]:
        print(f"  {c['breadth']:>4}/{result['corpus_sessions']:<3}  {c['breadth_pct']:>6.1f}%  "
              f"{c['total']:>6}  {c['signature']}")
    print(f"\nrecurrence table: {args.out}")


if __name__ == "__main__":
    main()
