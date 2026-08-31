#!/usr/bin/env python3
"""Metric-name extraction-recall measurement for supergoal's prior-arc guard.

A `build-measurement-harness` instance (see harness/PROBLEM.md). Drives the real
`scripts/parse_plan.extract_metric_names` across a labeled fixture of plan-markdown
snippets and measures whether supergoal actually delivers its headline value-prop —
"refuses re-litigation of prior arcs."

That guard (`scripts/check_prior_arcs.py`) keys ONLY on `metric_names` and silently
no-ops when the list is empty:

    if not metric_names:
        print("PRIOR-ARC: skipped (no metric_names extracted)")
        return 0

So a plan whose metrics the extractor misses gets NO prior-arc protection — the
ceremony is undelivered. We measure extraction RECALL: of the metric names a careful
human reads in each plan, what fraction does extract_metric_names actually return?
Each missed name is a hole the prior-arc ledger can never match against.

The oracle (fixture `oracle_metric_names`) is INDEPENDENT hand-derived ground truth,
NOT extract_metric_names' own output (see PROBLEM.md §2).

Deterministic + offline (extract_metric_names is a pure function over text;
no network, no keys, no state files).

Usage:
    python3 skills/supergoal/harness/measure.py [--json]
Exit code: 0 iff overall extraction recall >= TARGET_RECALL.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
SCRIPTS = HARNESS_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from parse_plan import extract_metric_names  # noqa: E402

TARGET_RECALL = 0.9  # the prior-arc guard must SEE the plan's metrics, not most-of-the-time
FIXTURE = HARNESS_DIR / "fixture.json"


def run_measurement(fixture_path: Path = FIXTURE) -> dict:
    """Run extract_metric_names over every fixture snippet; return measured metrics.

    Recall is reported two ways:
      - micro (overall): sum(hits) / sum(oracle names) across all snippets — the
        headline number, weighting each metric name equally.
      - macro: mean of per-snippet recall — weights each plan equally.
    """
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    target = fixture.get("target_recall", TARGET_RECALL)
    rows = []
    total_oracle = 0
    total_hits = 0
    per_snippet_recalls = []

    for sn in fixture["snippets"]:
        oracle = list(dict.fromkeys(sn["oracle_metric_names"]))  # de-dup, keep order
        extracted = extract_metric_names(sn["plan_md"])
        oracle_set = set(oracle)
        extracted_set = set(extracted)
        hits = sorted(oracle_set & extracted_set)
        missed = sorted(oracle_set - extracted_set)
        # Names the extractor returned that no human labeled a metric (noise/over-extraction).
        spurious = sorted(extracted_set - oracle_set)

        n_oracle = len(oracle_set)
        n_hit = len(hits)
        total_oracle += n_oracle
        total_hits += n_hit
        recall = (n_hit / n_oracle) if n_oracle else 1.0
        per_snippet_recalls.append(recall)

        # The prior-arc guard is ACTIVE iff metric_names is non-empty; otherwise
        # check_prior_arcs.py prints "skipped (no metric_names extracted)" and the
        # "refuses re-litigation" value-prop is NOT delivered for this plan.
        guard_active = bool(extracted_set)

        rows.append({
            "id": sn["id"],
            "style": sn.get("style", ""),
            "all_non_allcaps": bool(sn.get("all_non_allcaps", False)),
            "oracle_metric_names": oracle,
            "extracted_metric_names": sorted(extracted_set),
            "hits": hits,
            "missed": missed,
            "spurious": spurious,
            "recall": recall,
            "prior_arc_guard_active": guard_active,
        })

    micro_recall = (total_hits / total_oracle) if total_oracle else 1.0
    macro_recall = (sum(per_snippet_recalls) / len(per_snippet_recalls)) if per_snippet_recalls else 1.0

    silent_noops = [r["id"] for r in rows if not r["prior_arc_guard_active"]]
    # Snippets where a human reads metrics but the guard is dead (the value-prop hole).
    undelivered = [r["id"] for r in rows if r["oracle_metric_names"] and not r["prior_arc_guard_active"]]

    return {
        "target_recall": target,
        "n_snippets": len(rows),
        "total_oracle_names": total_oracle,
        "total_hits": total_hits,
        "recall": micro_recall,           # headline metric (micro / name-weighted)
        "macro_recall": macro_recall,     # plan-weighted, for context
        "guard_active_count": sum(r["prior_arc_guard_active"] for r in rows),
        "silent_noop_snippets": silent_noops,
        "undelivered_value_prop_snippets": undelivered,
        "rows": rows,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="supergoal prior-arc extraction-recall measurement")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args(argv)
    m = run_measurement()
    if args.json:
        print(json.dumps(m, indent=2))
    else:
        print("supergoal prior-arc extraction-recall measurement")
        print("(extract_metric_names vs INDEPENDENT hand-labeled oracle; guard no-ops on empty)")
        print()
        print(f"  {'snippet':<32} {'recall':>6} {'guard':>6} {'missed (held by no ledger)'}")
        for r in m["rows"]:
            guard = "ACTIVE" if r["prior_arc_guard_active"] else "NO-OP"
            missed = ",".join(r["missed"]) if r["missed"] else "-"
            print(f"  {r['id']:<32} {r['recall']:>6.0%} {guard:>6} {missed}")
        print()
        print(f"  extraction recall (micro) : {m['recall']:.1%}  "
              f"({m['total_hits']}/{m['total_oracle_names']} names; target >= {m['target_recall']:.0%})")
        print(f"  extraction recall (macro) : {m['macro_recall']:.1%}  (per-snippet mean)")
        print(f"  prior-arc guard active    : {m['guard_active_count']}/{m['n_snippets']} snippets")
        if m["undelivered_value_prop_snippets"]:
            print(f"  GUARD SILENTLY NO-OPS on  : {', '.join(m['undelivered_value_prop_snippets'])}")
            print("    -> these plans have human-readable metrics but get ZERO prior-arc")
            print("       protection: check_prior_arcs.py prints 'skipped (no metric_names)'.")
        verdict = "PASS" if m["recall"] >= m["target_recall"] else "FAIL"
        print(f"\n  gate: {verdict} (recall {m['recall']:.1%} {'>=' if verdict=='PASS' else '<'} {m['target_recall']:.0%})")
    return 0 if m["recall"] >= m["target_recall"] else 1


if __name__ == "__main__":
    sys.exit(main())
