#!/usr/bin/env python3
"""variant-analysis cross-hunt history — components 6 (memory) + 8 (observability).

Reads NDJSON event logs produced by `verify_variants.py --ndjson PATH` and:

1. `append`  — summarize a hunt verification into `hunt-history.jsonl`
   (one row per hunt: pattern levels, match counts, FP-gate status,
   baseline pass/fail). Hunts accumulate so future hunts can compare:
   does this codebase consistently produce high-FP patterns at level 3?
   Which root-cause families have the highest match density?

2. `diff`    — compare last two hunts. Useful for "we tightened the
   pattern; did variant count drop and FP rate improve?"

3. `summary` — aggregate stats: which kinds (rg / semgrep / codeql)
   have the highest baseline-miss rate, which root-causes recur, which
   levels typically trip the FP cap.

Usage:
    hunt_history.py append <ndjson-path> [--root-cause TEXT]
    hunt_history.py diff [--last N]
    hunt_history.py summary [--top N]
"""
import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HISTORY_PATH = REPO_ROOT / "skills" / "variant-analysis" / "hunt-history.jsonl"


def _git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=10", "HEAD"],
            cwd=REPO_ROOT, text=True, timeout=5,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def append(ndjson_path, root_cause):
    records = []
    try:
        with open(ndjson_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        print(f"ERROR: {ndjson_path} not found", file=sys.stderr)
        return 2

    if not records:
        print(f"ERROR: {ndjson_path} contains no parseable NDJSON records; refusing to append an empty hunt row",
              file=sys.stderr)
        print("hint: generate the log with verify_variants.py --ndjson <path>, then re-run append", file=sys.stderr)
        return 2

    by_check = {}
    for r in records:
        check = r.get("check", "?")
        if check not in by_check:
            by_check[check] = {"passed": True, "reason": None, "n": 0}
        by_check[check]["n"] += 1
        if not r.get("passed", True):
            by_check[check]["passed"] = False
            by_check[check]["reason"] = r.get("reason")

    n_matches_total = sum(r.get("n_matches", 0) for r in records if r.get("check") == "variant_run")
    run_ids = sorted({r.get("run_id") for r in records if r.get("run_id")})
    run_id = run_ids[-1] if run_ids else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    summary = {
        "run_id": run_id,
        "root_cause": root_cause or "<unspecified>",
        "git_sha": _git_sha(),
        "model": os.environ.get("CLAUDE_CODE_MODEL") or os.environ.get("CLAUDE_MODEL") or "<not-set>",
        "appended_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ndjson_source": str(ndjson_path),
        "n_matches_total": n_matches_total,
        "checks": {k: v["passed"] for k, v in sorted(by_check.items())},
        "n_failed": sum(1 for c in by_check.values() if not c["passed"]),
    }

    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as h:
        h.write(json.dumps(summary) + "\n")

    print(f"Appended hunt summary for root_cause={summary['root_cause']}, run {run_id}:")
    print(f"  Total matches across levels: {n_matches_total}")
    print(f"  Checks failed: {summary['n_failed']}")
    print(f"  History: {HISTORY_PATH.relative_to(REPO_ROOT)}")
    return 0


def _load_history():
    if not HISTORY_PATH.is_file():
        return []
    rows = []
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def diff(last_n):
    rows = _load_history()
    if len(rows) < last_n:
        print(f"Need >={last_n} history rows; have {len(rows)}.")
        return 1
    latest = rows[-1]
    prior = rows[-last_n]
    print(f"=== Hunt diff: {prior.get('root_cause')}@{prior.get('run_id')} -> "
          f"{latest.get('root_cause')}@{latest.get('run_id')} ===")
    print(f"  Matches:   {prior.get('n_matches_total', 0)} -> {latest.get('n_matches_total', 0)}"
          f" ({latest.get('n_matches_total', 0) - prior.get('n_matches_total', 0):+d})")
    print(f"  Failed:    {prior.get('n_failed', 0)} -> {latest.get('n_failed', 0)}")
    prior_checks = prior.get("checks", {})
    latest_checks = latest.get("checks", {})
    regressions = [c for c in set(prior_checks) | set(latest_checks)
                   if prior_checks.get(c, True) and not latest_checks.get(c, True)]
    if regressions:
        print("\nNew failures (regression):")
        for c in sorted(regressions):
            print(f"  {c}: passed -> FAILED")
    return 0


def summary(top_n):
    rows = _load_history()
    if not rows:
        print("No history yet. Run verify_variants.py --ndjson=run.ndjson, then "
              "hunt_history.py append run.ndjson.")
        return 1
    print(f"=== Hunt-history summary: {len(rows)} hunt(s) ===")
    check_failures = Counter()
    check_total = Counter()
    for row in rows:
        for check, passed in row.get("checks", {}).items():
            check_total[check] += 1
            if not passed:
                check_failures[check] += 1
    print(f"\nPer-check failure rates (top {top_n}):")
    for check, total in check_total.most_common(top_n):
        failures = check_failures[check]
        rate = failures / total if total else 0
        bar = "#" * int(rate * 10) + "." * (10 - int(rate * 10))
        print(f"  {check:<24}  {bar}  {failures}/{total} fails ({rate:.0%})")
    rc = Counter(r.get("root_cause", "?") for r in rows)
    print(f"\nRoot-causes hunted (top {top_n}):")
    for cause, n in rc.most_common(top_n):
        print(f"  {n}x  {cause}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub_append = sub.add_parser("append", help="Append a hunt-summary row from an NDJSON verification log")
    sub_append.add_argument("ndjson", help="Path to NDJSON file emitted by verify_variants.py --ndjson")
    sub_append.add_argument("--root-cause", default=None, help="Root-cause label (otherwise <unspecified>)")
    sub_diff = sub.add_parser("diff", help="Compare last two hunts")
    sub_diff.add_argument("--last", type=int, default=2)
    sub_sum = sub.add_parser("summary", help="Aggregate stats across all hunts")
    sub_sum.add_argument("--top", type=int, default=10)
    args = ap.parse_args()
    if args.cmd == "append":
        sys.exit(append(args.ndjson, args.root_cause))
    elif args.cmd == "diff":
        sys.exit(diff(args.last))
    elif args.cmd == "summary":
        sys.exit(summary(args.top))


if __name__ == "__main__":
    main()
