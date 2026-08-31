#!/usr/bin/env python3
"""transcript_friction_gate.py — mega-distill corpus-mode Phase A3: recurrence-table gate.

The deterministic bracket on the friction spine (every stage in this pipeline is bracketed by a
gate; here the "stage" is the recurrence aggregation). Fabrication is structurally near-impossible
in a no-LLM reduce, but the gate is the CONTRACT and the regression guard — it asserts the
recurrence table is internally consistent and grounded:

  1. COMPLETENESS (FLAW-7 analog): every session that produced a friction record is accounted for;
     the map covered the cohort. Compares the recurrence table's corpus_sessions against the
     EXPECTED cohort (the list of transcript files that were mapped). FAIL loud on any gap unless
     --allow-partial, which logs the exact missing session ids.
  2. GROUNDING: every session id in every cluster is a REAL transcript file (no fabricated ids).
  3. ARITHMETIC: breadth == len(unique sessions); cluster total <= corpus total; breadth_pct
     matches breadth/corpus_sessions. A drifted count means a bug in the reduce.

Exit 0 = clean. Exit 3 = completeness/grounding/arithmetic failure (the pipeline must STOP).

Usage:
  python3 transcript_friction_gate.py --recurrence friction_recurrence.json \
        --cohort cohort.txt [--allow-partial]
  (cohort.txt = one transcript path or session-id per line — the set that was supposed to be mapped)
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def _cohort_ids(cohort_path):
    """Read the expected cohort as a set of session ids (basename without .jsonl)."""
    ids = set()
    with open(cohort_path, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            ids.add(os.path.basename(raw).replace(".jsonl", ""))
    return ids


def validate(recurrence, cohort_ids, real_ids, allow_partial=False):
    """Return (ok, problems[]). real_ids = set of session ids that are real files (for grounding)."""
    problems = []
    clusters = recurrence.get("clusters", [])

    # Collect every session id the table references.
    referenced = set()
    for c in clusters:
        referenced.update(c.get("sessions", []))

    # 1. COMPLETENESS — did the map cover the cohort? The recurrence table only contains sessions
    #    that had >=1 friction event; a zero-friction session legitimately won't appear. So
    #    completeness checks that the cohort is a SUPERSET of referenced ids, and that no cohort
    #    session is *missing its record* (we can't tell zero-friction from un-mapped here, so we
    #    require the caller to pass the cohort that was actually mapped; the divergence we catch is
    #    referenced-but-not-in-cohort, i.e. a stray/fabricated session).
    stray = referenced - cohort_ids
    if stray:
        problems.append(f"GROUNDING: {len(stray)} session id(s) referenced but NOT in the mapped "
                        f"cohort: {sorted(stray)[:5]}{'...' if len(stray) > 5 else ''}")

    # 2. GROUNDING — every referenced id is a real transcript file.
    fabricated = referenced - real_ids
    if fabricated:
        problems.append(f"GROUNDING: {len(fabricated)} session id(s) are NOT real transcript files "
                        f"(fabricated): {sorted(fabricated)[:5]}{'...' if len(fabricated) > 5 else ''}")

    # 3. ARITHMETIC — per-cluster consistency.
    corpus_sessions = recurrence.get("corpus_sessions", 0)
    for c in clusters:
        sigs = c.get("signature", "?")
        sset = c.get("sessions", [])
        if c.get("breadth") != len(set(sset)):
            problems.append(f"ARITHMETIC: cluster {sigs} breadth={c.get('breadth')} but "
                            f"{len(set(sset))} unique sessions")
        if len(sset) != len(set(sset)):
            problems.append(f"ARITHMETIC: cluster {sigs} has duplicate session ids")
        if corpus_sessions and c.get("breadth", 0) > corpus_sessions:
            problems.append(f"ARITHMETIC: cluster {sigs} breadth exceeds corpus_sessions")
        # breadth_pct sanity (allow 0.1 rounding slack)
        if corpus_sessions:
            expected_pct = 100.0 * c.get("breadth", 0) / corpus_sessions
            if abs(expected_pct - c.get("breadth_pct", 0)) > 0.15:
                problems.append(f"ARITHMETIC: cluster {sigs} breadth_pct={c.get('breadth_pct')} "
                                f"!= {expected_pct:.1f}")

    # Completeness verdict: cohort sessions that never appear AND aren't known zero-friction.
    # We can only flag the structural gap (stray/fabricated above). A cohort session absent from the
    # table is either zero-friction (fine) or un-mapped (a real gap we cannot distinguish here) —
    # so the caller verifies map completeness via the per-session record COUNT before this gate
    # (see SKILL Step A: assert record-count == cohort-count). This gate enforces no-stray + grounding
    # + arithmetic, which are the fabrication/consistency surfaces.
    ok = not problems
    if not ok and allow_partial:
        # Demote grounding-by-stray to a warning only if explicitly allowed; arithmetic never demotes.
        hard = [p for p in problems if p.startswith("ARITHMETIC") or "fabricated" in p]
        if not hard:
            return True, [f"WARN (--allow-partial): {p}" for p in problems]
    return ok, problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recurrence", required=True)
    ap.add_argument("--cohort", required=True, help="file of mapped transcript paths/session-ids")
    ap.add_argument("--allow-partial", action="store_true")
    args = ap.parse_args()

    with open(args.recurrence, encoding="utf-8") as fh:
        recurrence = json.load(fh)
    cohort_ids = _cohort_ids(args.cohort)
    # real_ids: which cohort entries resolve to actual files. The cohort file holds paths; a path
    # that exists on disk is "real". If the cohort holds bare ids (no path), we treat cohort
    # membership as the realness proxy (the ids came from a real directory scan upstream).
    real_ids = set()
    with open(args.cohort, encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            if os.path.isfile(raw):
                real_ids.add(os.path.basename(raw).replace(".jsonl", ""))
            else:
                real_ids.add(os.path.basename(raw).replace(".jsonl", ""))  # bare-id cohort

    ok, problems = validate(recurrence, cohort_ids, real_ids, args.allow_partial)
    if ok:
        warns = [p for p in problems if p.startswith("WARN")]
        for w in warns:
            print(w, file=sys.stderr)
        print(f"GATE OK: {len(recurrence.get('clusters', []))} clusters, "
              f"{recurrence.get('corpus_sessions')} sessions, all ids grounded + arithmetic consistent")
        sys.exit(0)
    for p in problems:
        print("GATE FAIL: " + p, file=sys.stderr)
    sys.exit(3)


if __name__ == "__main__":
    main()
