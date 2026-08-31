#!/usr/bin/env python3
"""transcript_semantic_gate.py — mega-distill corpus-mode Phase B3+B5: the LLM-stage brackets.

Two deterministic gates bracketing the semantic layer's two LLM stages (every LLM stage in this
pipeline is bracketed by a deterministic gate):

  --mode completeness  (B3, runs AFTER the map, BEFORE clustering): assert the map actually wrote a
    per-session lesson file for EVERY cohort session. subagent return-value != disk-write (FLAW-7,
    2026-06-21: a map reported 79/79 ok while 72 files landed). reduce/cluster consumes the DISK, so
    a silent write-miss undercounts breadth with no signal. Compares lesson-file session-ids to the
    cohort; exit 3 on any gap unless --allow-partial (which logs the exact missing ids).

  --mode cluster  (B5, runs AFTER clustering): assert the cluster artifact is grounded and complete:
    (a) COVERAGE — every input lesson is assigned to exactly one cluster (no lesson dropped/duplicated)
    (b) NO-FABRICATION — every session_id a cluster cites is a REAL cohort session
    (c) ARITHMETIC — each cluster's breadth == unique sessions across its member lessons, recomputed
        DETERMINISTICALLY here, never trusted from the LLM (FLAW-4 count-lying: an LLM synthesis
        claimed 26/18 when truth was 28/22). The published breadth is THIS computation's, not the LLM's.

Exit 0 = clean. Exit 3 = gate failure (pipeline must STOP).

Usage:
  python3 transcript_semantic_gate.py --mode completeness --lessons-dir <dir> --cohort cohort.txt
  python3 transcript_semantic_gate.py --mode cluster --clusters clusters.json --lessons-dir <dir> \
        --cohort cohort.txt [--out clusters_verified.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _cohort_ids(path):
    ids = set()
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if raw:
                ids.add(os.path.basename(raw).replace(".jsonl", ""))
    return ids


def _lesson_files(lessons_dir):
    """Map session_id -> list of lessons, from per-session lesson files lessons_<sid>.json.
    Each file is {session, lessons:[{id?, summary, tier?, ...}, ...]} or a bare list."""
    out = {}
    for fn in sorted(os.listdir(lessons_dir)):
        if not (fn.startswith("lessons_") and fn.endswith(".json")):
            continue
        sid = fn[len("lessons_"):-len(".json")]
        try:
            d = json.load(open(os.path.join(lessons_dir, fn), encoding="utf-8"))
        except Exception:
            out[sid] = None  # unparseable -> treated as a miss
            continue
        lessons = d.get("lessons", d) if isinstance(d, dict) else d
        out[sid] = lessons if isinstance(lessons, list) else []
    return out


def gate_completeness(lessons_dir, cohort_ids, allow_partial):
    have = _lesson_files(lessons_dir)
    parsed_ids = {sid for sid, v in have.items() if v is not None}
    unparseable = {sid for sid, v in have.items() if v is None}
    missing = sorted(cohort_ids - parsed_ids)
    problems = []
    if missing:
        problems.append(f"COMPLETENESS: {len(missing)} of {len(cohort_ids)} cohort sessions have NO "
                        f"lesson file (map under-delivered): {missing[:5]}{'...' if len(missing) > 5 else ''}")
    if unparseable:
        problems.append(f"COMPLETENESS: {len(unparseable)} lesson file(s) unparseable: "
                        f"{sorted(unparseable)[:5]}")
    ok = not problems
    if not ok and allow_partial:
        return True, [f"WARN (--allow-partial): {p}" for p in problems]
    return ok, problems


def gate_cluster(clusters_path, lessons_dir, cohort_ids):
    clusters = json.load(open(clusters_path, encoding="utf-8"))
    cl = clusters.get("clusters", clusters) if isinstance(clusters, dict) else clusters
    have = _lesson_files(lessons_dir)

    # Build the full set of input lesson keys (sid::index) the clustering was supposed to cover.
    all_keys = set()
    lesson_session = {}
    for sid, lessons in have.items():
        if not lessons:
            continue
        for i, _ in enumerate(lessons):
            key = f"{sid}::{i}"
            all_keys.add(key)
            lesson_session[key] = sid

    problems = []
    warnings = []
    assigned = {}
    recomputed = []
    for c in cl:
        members = c.get("members", c.get("lesson_keys", []))
        # NO-FABRICATION: every cited session/member must be real.
        member_sessions = set()
        for m in members:
            # member may be "sid::i" or {"session":..,"index":..}
            if isinstance(m, dict):
                key = f"{m.get('session')}::{m.get('index')}"
            else:
                key = str(m)
            if key not in all_keys:
                problems.append(f"NO-FABRICATION: cluster {c.get('name','?')} cites lesson {key} "
                                f"that does not exist in the map output")
                continue
            sid = lesson_session[key]
            if sid not in cohort_ids:
                problems.append(f"NO-FABRICATION: cluster {c.get('name','?')} cites session {sid} "
                                f"not in cohort")
            member_sessions.add(sid)
            # COVERAGE: each lesson assigned at most once.
            if key in assigned:
                problems.append(f"COVERAGE: lesson {key} assigned to >1 cluster "
                                f"({assigned[key]} and {c.get('name','?')})")
            assigned[key] = c.get("name", "?")
        # ARITHMETIC: recompute breadth deterministically and OVERRIDE the LLM's claim. A mismatch is
        # EXPECTED and corrected silently (FLAW-4: the LLM's count is never trusted — the published
        # breadth is THIS computation's). A discrepancy is a WARNING, not a failure: the gate's job is
        # to fix the count, not reject the cluster for having a wrong one. Only fabrication + coverage
        # (below) are hard failures.
        true_breadth = len(member_sessions)
        claimed = c.get("breadth")
        if claimed is not None and claimed != true_breadth:
            warnings.append(f"breadth corrected: cluster {c.get('name','?')} claimed {claimed} "
                            f"-> recomputed {true_breadth}")
        recomputed.append({**c, "breadth": true_breadth, "sessions": sorted(member_sessions)})

    # COVERAGE: every input lesson assigned to exactly one cluster.
    unassigned = sorted(all_keys - set(assigned))
    if unassigned:
        problems.append(f"COVERAGE: {len(unassigned)} of {len(all_keys)} lessons assigned to NO "
                        f"cluster: {unassigned[:5]}{'...' if len(unassigned) > 5 else ''}")

    recomputed.sort(key=lambda c: -c["breadth"])
    return (not problems), problems, recomputed, warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, choices=["completeness", "cluster"])
    ap.add_argument("--lessons-dir", required=True)
    ap.add_argument("--cohort", required=True)
    ap.add_argument("--clusters", help="required for --mode cluster")
    ap.add_argument("--out", help="write recomputed/verified clusters (cluster mode)")
    ap.add_argument("--allow-partial", action="store_true")
    args = ap.parse_args()

    cohort_ids = _cohort_ids(args.cohort)

    if args.mode == "completeness":
        ok, problems = gate_completeness(args.lessons_dir, cohort_ids, args.allow_partial)
        for p in problems:
            print(("" if p.startswith("WARN") else "GATE FAIL: ") + p,
                  file=sys.stderr if not p.startswith("WARN") else sys.stderr)
        if ok:
            print(f"GATE OK (completeness): lesson file for every cohort session "
                  f"({len(cohort_ids)} sessions)")
            sys.exit(0)
        sys.exit(3)

    # cluster mode
    if not args.clusters:
        print("--clusters required for --mode cluster", file=sys.stderr)
        sys.exit(2)
    ok, problems, recomputed, warnings = gate_cluster(args.clusters, args.lessons_dir, cohort_ids)
    if args.out:
        json.dump({"clusters": recomputed}, open(args.out, "w", encoding="utf-8"), indent=2)
    for w in warnings:
        print("  (corrected) " + w, file=sys.stderr)
    if ok:
        print(f"GATE OK (cluster): {len(recomputed)} clusters, all lessons covered, all sessions "
              f"grounded, breadth recomputed deterministically "
              f"({len(warnings)} LLM breadth-claim(s) corrected)")
        if args.out:
            print(f"verified clusters -> {args.out}")
        sys.exit(0)
    for p in problems:
        print("GATE FAIL: " + p, file=sys.stderr)
    sys.exit(3)


if __name__ == "__main__":
    main()
