#!/usr/bin/env python3
"""Offline re-grade of saved deep-dive A/B records with the CURRENT grade.py.

NO API calls, NO network. Reads a `runs/transcripts-<ts>.json` or a
`runs/sample-records-<date>.json` ({"model_catalog": [...], "runs": [...]}; records
made before 2026-09-04 are a bare LIST of {"run_idx", "records"} or {"runs": [...]}
without a snapshot) and re-scores every record with the grader as it stands now, so
a grader/oracle correction can be applied to records that were already paid for
(Phase-9: verify the instrument before trusting a verdict). The frozen 2026-05-31
results.json is never written.

The `current-anthropic-model` key is re-derived from the run's RECORDED vendor model
list (grade.catalog_key), never fetched here; records without a snapshot fall back to
the fixture's dated keys and the output says so (`current_model_key: null`).

Usage:
    python3 regrade.py --records runs/transcripts-20260903T205439Z.json \
        --run-date 2026-09-03 --model claude-fable-5-1 \
        --output runs/regrade-2026-09-03.json \
        [--sample-out runs/sample-records-2026-09-03.json]

--run-date selects the dated answer key for currency questions (grade.key_for);
use the date the records were produced. --sample-out writes the compact,
re-gradeable sample (records minus `_response_provenance`, plus the snapshot) the
test suite reads.
"""
from __future__ import annotations

import argparse
import json
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
EXTRA_KEYS = ("calibration_discrimination_all",)
DROP_FROM_SAMPLE = ("_response_provenance",)


def load_records(path: Path) -> tuple[list[dict], list[dict] | None]:
    """Returns (runs, model_catalog); model_catalog is None for records made before snapshots."""
    data = json.loads(path.read_text(encoding="utf-8"))
    runs = data["runs"] if isinstance(data, dict) else data
    if not isinstance(runs, list) or not runs or not all("records" in r for r in runs):
        raise ValueError(f"{path}: expected a list of {{run_idx, records}} or {{'runs': [...]}}")
    catalog = data.get("model_catalog") if isinstance(data, dict) else None
    return runs, (catalog or None)


def regrade(fixture: dict, runs: list[dict], run_date: str,
            model_catalog: list[dict] | None = None) -> tuple[dict, dict, dict]:
    """Returns (aggregates per arm, verdict, per-question table)."""
    per_arm = {a: [] for a in ARMS}
    per_q: dict = {q["id"]: {"kind": q["kind"], "currency": bool(q.get("currency")),
                             "key_source": grade.key_source(q, model_catalog),
                             **{a: {"correct": [], "confidence": [], "key_expired": []} for a in ARMS}}
                   for q in fixture["questions"]}
    for run in runs:
        for a in ARMS:
            scored = grade.score_run(fixture, [r for r in run["records"] if r["arm"] == a],
                                     run_date=run_date, model_catalog=model_catalog)
            per_arm[a].append(scored)
            for row in scored["rows"]:
                cell = per_q[row["id"]][a]
                cell["correct"].append(row["correct"])
                cell["confidence"].append(row["confidence"])
                cell["key_expired"].append(row["key_expired"])
    keys = tuple(grade._METRIC_KEYS) + EXTRA_KEYS
    agg = {a: grade.aggregate_runs(per_arm[a], keys=keys) for a in ARMS}
    if grade.stats is not None:
        grade.stats.attach_ci(agg["with_skill"], agg["baseline"], keys)
    verdict = grade.decide_verdict(agg["with_skill"], agg["baseline"], min_delta=0.05)
    return agg, verdict, per_q


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="offline re-grade of saved deep-dive A/B records (no API calls)")
    ap.add_argument("--records", type=Path, required=True, help="transcripts-*.json or sample-records-*.json")
    ap.add_argument("--run-date", required=True, help="YYYY-MM-DD the records were produced (selects dated keys)")
    ap.add_argument("--model", required=True, help="model id the records were produced on (recorded, not verified)")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--sample-out", type=Path, default=None,
                    help="also write the compact re-gradeable sample (records minus _response_provenance)")
    args = ap.parse_args(argv)
    output = args.output.expanduser().resolve()
    if output == FROZEN_RESULTS.resolve():
        ap.error("the frozen 2026-05-31 results.json is immutable; write the re-grade elsewhere")
    if not grade._ISO_DATE.match(args.run_date):
        ap.error("--run-date must be YYYY-MM-DD")
    records_path = args.records.expanduser().resolve()
    if not records_path.is_file():
        print(f"error: records file not found: {records_path}", file=sys.stderr)
        return 2
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    runs, model_catalog = load_records(records_path)
    agg, verdict, per_q = regrade(fixture, runs, args.run_date, model_catalog)
    n_questions = len({r["id"] for run in runs for r in run["records"]})
    frozen = json.loads(FROZEN_RESULTS.read_text(encoding="utf-8")) if FROZEN_RESULTS.exists() else {}
    fixture_sha = sha256(FIXTURE.read_bytes()).hexdigest()[:12]
    results = {
        "_about": (f"OFFLINE RE-GRADE (no API calls) of {records_path.name} with grade.py at fixture "
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
        # The recorded snapshot the key was derived from; null means the records predate
        # snapshots and `current-anthropic-model` was graded against the legacy dated key.
        "model_catalog": model_catalog,
        "current_model_key": grade.catalog_key(model_catalog) if model_catalog else None,
        "arms": frozen.get("arms", "with_skill (3-layer framework) vs baseline (plain + confidence)"),
        "run_date": args.run_date, "n_runs": len(runs), "n_questions": n_questions,
        "fixture_sha": fixture_sha, "cost_ratio": frozen.get("cost_ratio"),
        "metrics": agg, "verdict": verdict, "per_question": per_q,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    if args.sample_out is not None:
        sample_out = args.sample_out.expanduser().resolve()
        if sample_out == FROZEN_RESULTS.resolve():
            ap.error("refusing to overwrite the frozen results.json with a sample")
        compact = {"_about": ("Compact re-gradeable sample (records minus _response_provenance) of "
                              f"{records_path.name}; regrade.py --records <this file> --run-date {args.run_date} "
                              f"reproduces {output.name}."),
                   "runs": [{"run_idx": run["run_idx"],
                             "records": [{k: v for k, v in rec.items() if k not in DROP_FROM_SAMPLE}
                                         for rec in run["records"]]} for run in runs]}
        if model_catalog:
            compact["model_catalog"] = model_catalog
        sample_out.write_text(json.dumps(compact, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": verdict,
                      "with_skill": {k: agg["with_skill"].get(k) for k in grade._METRIC_KEYS},
                      "baseline": {k: agg["baseline"].get(k) for k in grade._METRIC_KEYS}}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
