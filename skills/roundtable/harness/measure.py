#!/usr/bin/env python3
"""Consensus-integrity measurement for roundtable's convergence auto-stop.

A `build-measurement-harness` instance (see harness/PROBLEM.md). Drives the real
`scripts/embed.should_stop` across a labeled scenario fixture and measures whether
the auto-stop delivers a decorrelated multi-vendor consensus or declares one when
the roundtable has collapsed to a sub-quorum of surviving vendors.

Deterministic + offline (should_stop is a pure function; no network/keys).

Usage:
    python3 skills/roundtable/harness/measure.py [--json]
Exit code: 0 iff false_consensus_count == 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
SCRIPTS = HARNESS_DIR.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from embed import should_stop  # noqa: E402

MIN_QUORUM = 2  # >= 2 distinct vendors required for a decorrelated consensus
FIXTURE = HARNESS_DIR / "fixture.json"


def run_measurement(fixture_path: Path = FIXTURE) -> dict:
    """Run should_stop over every fixture scenario; return measured metrics."""
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    rows = []
    for sc in fixture["scenarios"]:
        sims = sc["sims"]  # dict | None (JSON null -> None)
        stop, reason = should_stop(sc["round_num"], sc["min_rounds"], sc["threshold"], sims)
        n_vendors = 0 if sims is None else len(sims)
        rows.append({
            "id": sc["id"],
            "class": sc["class"],
            "n_vendors": n_vendors,
            "stop": bool(stop),
            "oracle_stop": bool(sc["oracle_stop"]),
            "correct": bool(stop) == bool(sc["oracle_stop"]),
            # False consensus: auto-stopped on a collapse scenario (sub-quorum).
            "false_consensus": bool(stop) and sc["class"] == "collapse",
            "reason": reason,
        })

    collapse = [r for r in rows if r["class"] == "collapse"]
    true_consensus = [r for r in rows if r["class"] == "true_consensus"]
    continues = [r for r in rows if r["class"] == "correctly_continues"]
    false_consensus_count = sum(r["false_consensus"] for r in rows)

    def rate(num, denom):
        return (num / denom) if denom else 0.0

    return {
        "min_quorum": MIN_QUORUM,
        "n_scenarios": len(rows),
        "false_consensus_count": false_consensus_count,
        "false_consensus_rate": rate(false_consensus_count, len(collapse)),
        "consensus_recall": rate(sum(r["stop"] for r in true_consensus), len(true_consensus)),
        "continue_correct_rate": rate(sum(not r["stop"] for r in continues), len(continues)),
        "integrity": rate(sum(r["correct"] for r in rows), len(rows)),
        "rows": rows,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="roundtable consensus-integrity measurement")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args(argv)
    m = run_measurement()
    if args.json:
        print(json.dumps(m, indent=2))
    else:
        print("roundtable consensus-integrity measurement (should_stop vs oracle)")
        print(f"  {'scenario':<18} {'class':<20} {'vendors':>7} {'stop':>5} {'oracle':>7} {'ok':>4}")
        for r in m["rows"]:
            flag = "FALSE-CONSENSUS" if r["false_consensus"] else ("" if r["correct"] else "MISS")
            print(f"  {r['id']:<18} {r['class']:<20} {r['n_vendors']:>7} "
                  f"{str(r['stop']):>5} {str(r['oracle_stop']):>7} {('ok' if r['correct'] else 'X'):>4}  {flag}")
        print(f"\n  false_consensus_count : {m['false_consensus_count']}  (target 0)")
        print(f"  false_consensus_rate  : {m['false_consensus_rate']:.0%}  (of collapse scenarios)")
        print(f"  consensus_recall      : {m['consensus_recall']:.0%}  (true consensus correctly stopped)")
        print(f"  integrity             : {m['integrity']:.0%}  (should_stop == oracle)")
    return 0 if m["false_consensus_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
