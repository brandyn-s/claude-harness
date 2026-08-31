#!/usr/bin/env python3
"""transcript_synth_check.py — deterministic verification gate for the Pass-2 LLM synthesis.

A synthesis agent merges semantic-duplicate findings within a bucket, but its SELF-REPORTED
counts and its claim of "nothing lost" are not evidence (live-test FLAW-4, 2026-06-20: a synthesis
agent reported input_count=26 / synthesized=18 when the real numbers were 28 / 22 — the merge work
was correct but the metadata was wrong). This gate checks the synthesis the same way
transcript_ground_check checks the extraction: deterministically, against the source.

Two invariants:
  COVERAGE   — every input ground appears in the output as either a kept `ground` or inside some
               finding's `merged_from`. A missing input ground = a SILENTLY DROPPED finding.
  NO-FABRICATION — every output `ground` and `merged_from` entry is a real input ground (the
               synthesis must not invent record citations).
Also recomputes the true input/output counts (ignoring the agent's self-report).

Exit 0 iff COVERAGE complete AND no fabrication. Exit 1 otherwise (lists the offenders).

Usage:
  python3 transcript_synth_check.py --input <synth_in_BUCKET.json> --output <synth_out_BUCKET.json>
"""
import argparse
import json
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="the bucket's Pass-2 INPUT list (synth_in_*.json)")
    ap.add_argument("--output", required=True, help="the synthesis agent's OUTPUT (synth_out_*.json)")
    args = ap.parse_args()

    inp = json.load(open(args.input, encoding="utf-8"))
    out = json.load(open(args.output, encoding="utf-8"))
    findings = out["findings"] if isinstance(out, dict) and "findings" in out else out

    # The valid reference set is the TRANSITIVE closure of input grounds: each input item's
    # top-level `ground` PLUS every record in its `merged_from`. This matters for HIERARCHICAL
    # synthesis (cross-shard merge): a per-shard pass already merged records into `merged_from`, so
    # those records are legitimate grounds the next stage may cite even though they're no longer a
    # top-level `ground`. Comparing against top-level grounds only would false-flag them as
    # fabricated (observed live, cross-shard insights merge 2026-06-21: 13/13 "fabrications" were
    # all nested merged_from entries). The closure is the correct provenance set.
    in_grounds = set()
    for i in inp:
        if i.get("ground"):
            in_grounds.add(i["ground"])
        for m in i.get("merged_from", []):
            in_grounds.add(m)
    out_grounds = set(f["ground"] for f in findings if f.get("ground"))
    merged = set(m for f in findings for m in f.get("merged_from", []))
    accounted = out_grounds | merged

    dropped = sorted(in_grounds - accounted)            # COVERAGE violations
    fabricated = sorted((out_grounds | merged) - in_grounds)  # NO-FABRICATION violations

    report = {
        "input_count_actual": len(inp),
        "input_count_reported": (out.get("input_count") if isinstance(out, dict) else None),
        "output_count_actual": len(findings),
        "output_count_reported": (out.get("synthesized_count") if isinstance(out, dict) else None),
        "coverage_complete": not dropped,
        "no_fabrication": not fabricated,
        "dropped_grounds": dropped,
        "fabricated_grounds": fabricated,
    }
    print(json.dumps(report, indent=2))
    if report["input_count_reported"] not in (None, len(inp)):
        print(f"NOTE: agent mis-reported input_count ({report['input_count_reported']} vs {len(inp)}) "
              f"— counts recomputed deterministically.", file=sys.stderr)
    sys.exit(0 if (not dropped and not fabricated) else 1)


if __name__ == "__main__":
    main()
