#!/usr/bin/env python3
"""Offline re-grade of saved gather-intel A/B records with the CURRENT grade.py.

NO API calls, NO network, NO grounding fetches: the saved records already carry the
`grounded` flag computed at run time; this only re-applies the verdict/oracle logic
(e.g. a claim newly marked `groundable: false`). Reads a `runs/transcripts-<ts>.json`
(a LIST of {"run_idx", "records"}) or a `runs/sample-records-<date>.json`
({"runs": [...]}). The frozen 2026-05-31 results.json is never written.

Usage:
    python3 regrade.py --records runs/transcripts-20260903T211607Z.json \
        --run-date 2026-09-03 --model claude-fable-5-1 \
        --output runs/regrade-2026-09-03.json \
        [--sample-out runs/sample-records-2026-09-03.json]

--sample-out writes the compact, re-gradeable sample (records minus `_text`) the
test suite reads (see README.md).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

HARNESS = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS))
import grade  # type: ignore

FIXTURE = HARNESS / "fixture.json"
FROZEN_RESULTS = HARNESS / "results.json"
ARMS = ("with_skill", "baseline")
DROP_FROM_SAMPLE = ("_text",)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_runs(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    runs = data["runs"] if isinstance(data, dict) else data
    if not isinstance(runs, list) or not runs or not all("records" in r for r in runs):
        raise ValueError(f"{path}: expected a list of {{run_idx, records}} or {{'runs': [...]}}")
    return runs


def regrade(fixture: dict, runs: list[dict], primary_metric: str, cost_ratio: float) -> tuple[dict, dict, dict]:
    per_arm = {a: [] for a in ARMS}
    per_claim: dict = {c["id"]: {"category": c["category"], "expected": c["expected_disposition"],
                                 "groundable": bool(c.get("groundable", True)),
                                 **{a: {"raw_verdict": [], "correct": [], "grounded": []} for a in ARMS}}
                       for c in fixture["claims"]}
    for run in runs:
        for a in ARMS:
            scored = grade.score_run(fixture, [r for r in run["records"] if r["arm"] == a])
            per_arm[a].append(scored)
            for row in scored["rows"]:
                cell = per_claim[row["id"]][a]
                cell["raw_verdict"].append(row["raw_verdict"])
                cell["correct"].append(row["correct"])
                cell["grounded"].append(row["grounded"])
    agg = {a: grade.aggregate_runs(per_arm[a]) for a in ARMS}
    if grade.stats is not None:
        grade.stats.attach_ci(agg["with_skill"], agg["baseline"], grade._METRIC_KEYS)
    verdict = grade.decide_verdict(agg["with_skill"], agg["baseline"], primary_metric, cost_ratio, min_delta=0.05)
    return agg, verdict, per_claim


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="offline re-grade of saved gather-intel A/B records (no API calls)")
    ap.add_argument("--records", type=Path, required=True, help="transcripts-*.json or sample-records-*.json")
    ap.add_argument("--run-date", required=True, help="YYYY-MM-DD the records were produced (recorded)")
    ap.add_argument("--model", required=True, help="model id the records were produced on (recorded, not verified)")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--sample-out", type=Path, default=None,
                    help="also write the compact re-gradeable sample (records minus _text)")
    args = ap.parse_args(argv)
    output = args.output.expanduser().resolve()
    if output == FROZEN_RESULTS.resolve():
        ap.error("the frozen 2026-05-31 results.json is immutable; write the re-grade elsewhere")
    if not _ISO_DATE.match(args.run_date):
        ap.error("--run-date must be YYYY-MM-DD")
    records_path = args.records.expanduser().resolve()
    if not records_path.is_file():
        print(f"error: records file not found: {records_path}", file=sys.stderr)
        return 2
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    frozen = json.loads(FROZEN_RESULTS.read_text(encoding="utf-8")) if FROZEN_RESULTS.exists() else {}
    primary_metric = frozen.get("primary_metric", "grounding_precision")
    cost_ratio = frozen.get("cost_ratio", 5.0)
    runs = load_runs(records_path)
    agg, verdict, per_claim = regrade(fixture, runs, primary_metric, cost_ratio)
    fixture_sha = sha256(FIXTURE.read_bytes()).hexdigest()[:12]
    categories: dict = {}
    for c in fixture["claims"]:
        categories[c["category"]] = categories.get(c["category"], 0) + 1
    results = {
        "_about": (f"OFFLINE RE-GRADE (no API calls, no fetches) of {records_path.name} with grade.py at fixture "
                   f"revision {fixture_sha}; the frozen 2026-05-31 results.json is untouched. "
                   "Reproduce: python3 regrade.py --records <this sample> --run-date <run_date> ..."),
        "regrade": {
            "records_file": records_path.name,
            "records_sha256": sha256(records_path.read_bytes()).hexdigest(),
            "run_date": args.run_date,
            "grader": "grade.py",
            "fixture_sha": fixture_sha,
            "regraded_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "frozen_results_sha256": sha256(FROZEN_RESULTS.read_bytes()).hexdigest() if FROZEN_RESULTS.exists() else None,
        },
        "model": args.model,
        "arms": frozen.get("arms", "with_skill (framework) vs baseline (plain strong pass)"),
        "run_date": args.run_date, "n_runs": len(runs),
        "n_claims": len({r["id"] for run in runs for r in run["records"]}),
        "fixture_sha": fixture_sha, "primary_metric": primary_metric, "cost_ratio": cost_ratio,
        "metrics": agg, "verdict": verdict, "per_category_n": categories, "per_claim": per_claim,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    if args.sample_out is not None:
        sample_out = args.sample_out.expanduser().resolve()
        if sample_out == FROZEN_RESULTS.resolve():
            ap.error("refusing to overwrite the frozen results.json with a sample")
        compact = {"_about": (f"Compact re-gradeable sample (records minus _text) of {records_path.name}; "
                              f"regrade.py --records <this file> --run-date {args.run_date} reproduces {output.name}."),
                   "runs": [{"run_idx": run["run_idx"],
                             "records": [{k: v for k, v in rec.items() if k not in DROP_FROM_SAMPLE}
                                         for rec in run["records"]]} for run in runs]}
        sample_out.write_text(json.dumps(compact, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": verdict,
                      "with_skill": {k: agg["with_skill"].get(k) for k in grade._METRIC_KEYS},
                      "baseline": {k: agg["baseline"].get(k) for k in grade._METRIC_KEYS}}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
