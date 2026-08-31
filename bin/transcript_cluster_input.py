#!/usr/bin/env python3
"""transcript_cluster_input.py — mega-distill corpus-mode Phase B4 prep: gather per-session lessons
into one clustering-input file (deterministic; the LLM clustering pass reads this).

After the semantic map (B2) writes lessons_<sid>.json per session and the completeness gate (B3)
passes, this collates every lesson into a single flat list with a stable key (sid::index) so the
clustering pass can reference lessons unambiguously and the cluster gate (B5) can verify coverage
(every key assigned) and no-fabrication (every cited key real). Deterministic — no judgment here.

Emits cluster_input.json: {n_sessions, n_lessons, lessons:[{key, session, summary, kind, root_cause,
proposed_fix, tier_hint, evidence}]}.

Usage:
  python3 transcript_cluster_input.py --lessons-dir <dir> --out cluster_input.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def collate(lessons_dir):
    flat = []
    sessions = set()
    for fn in sorted(os.listdir(lessons_dir)):
        if not (fn.startswith("lessons_") and fn.endswith(".json")):
            continue
        sid = fn[len("lessons_"):-len(".json")]
        try:
            d = json.load(open(os.path.join(lessons_dir, fn), encoding="utf-8"))
        except Exception:
            continue
        lessons = d.get("lessons", []) if isinstance(d, dict) else (d if isinstance(d, list) else [])
        sessions.add(sid)
        for i, le in enumerate(lessons):
            if not isinstance(le, dict):
                continue
            flat.append({
                "key": f"{sid}::{i}",
                "session": sid,
                "summary": le.get("summary", ""),
                "kind": le.get("kind", ""),
                "root_cause": le.get("root_cause", ""),
                "proposed_fix": le.get("proposed_fix", ""),
                "tier_hint": le.get("tier_hint", ""),
                "evidence": le.get("evidence", ""),
            })
    return {"n_sessions": len(sessions), "n_lessons": len(flat), "lessons": flat}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lessons-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    result = collate(args.lessons_dir)
    json.dump(result, open(args.out, "w", encoding="utf-8"), indent=2)
    print(f"collated {result['n_lessons']} lessons from {result['n_sessions']} sessions -> {args.out}")
    # by-kind histogram (a cheap preview of where clustering will concentrate)
    by_kind = {}
    for le in result["lessons"]:
        by_kind[le["kind"]] = by_kind.get(le["kind"], 0) + 1
    for k, v in sorted(by_kind.items(), key=lambda kv: -kv[1]):
        print(f"  {v:>4}  {k}")
    if result["n_lessons"] == 0:
        print("WARNING: no lessons collated", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
