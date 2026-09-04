#!/usr/bin/env python3
"""audit-skill cross-run history — components 6 (memory) + 8 (observability).

Reads NDJSON event logs produced by `audit-skill.py --ndjson=PATH` and:

1. `append` subcommand: summarize a run into `audit-history.jsonl` — one
   row per --all run with per-code finding counts, drift/error totals,
   git SHA, model version. Pattern memory accumulates here; future audits
   can detect new failure classes vs recurring ones.

2. `diff` subcommand: compare the last two history rows and print:
   - Codes that appeared in the latest run but not the prior (regressions)
   - Codes that disappeared (resolved)
   - Per-code count deltas
   This is the "memory" that connects component 8 (event log) to actual
   skill-design improvements.

3. `summary` subcommand: print aggregate statistics across all rows —
   which finding codes are repeat offenders (fire on every run), which
   skills accumulate the most findings over time.

Usage:
    audit_history.py append <ndjson-path>
    audit_history.py diff [--last N]                # default N=2
    audit_history.py summary [--top N]              # default N=10
"""
import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HISTORY_PATH = REPO_ROOT / "skills" / "audit-skill" / "audit-history.jsonl"


def _git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=10", "HEAD"],
            cwd=REPO_ROOT, text=True, timeout=5,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _model_provenance(records=None):
    """Record requested and effective runtime facts without guessing."""
    receipt = next(
        (
            record["runtime_receipt"]
            for record in reversed(records or [])
            if isinstance(record.get("runtime_receipt"), dict)
        ),
        {},
    )

    def observed(name):
        value = receipt.get(name)
        return value if value is not None and value != "" else "<unavailable>"

    requested = observed("requested_model")
    requested_source = "runtime_receipt"
    if requested == "<unavailable>":
        requested = os.environ.get("CLAUDE_MODEL") or "<unavailable>"
        requested_source = "environment" if requested != "<unavailable>" else "unavailable"

    effective = observed("effective_model")
    effective_source = observed("effective_model_source")
    if effective == "<unavailable>":
        effective_source = "unavailable"
    elif effective_source == "<unavailable>":
        effective_source = "runtime_receipt"

    return {
        "requested_model": requested,
        "requested_model_source": requested_source,
        "effective_model": effective,
        "effective_model_source": effective_source,
        "provider": observed("provider"),
        "effort": observed("effort"),
        "context_class": observed("context_class"),
        "claude_code_version": observed("claude_code_version"),
        "fallback": observed("fallback"),
        "refusal": observed("refusal"),
    }


def append(ndjson_path):
    """Summarize the NDJSON event log into one history row."""
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
        print(f"WARNING: {ndjson_path} contains no records — appending empty summary", file=sys.stderr)

    by_code = Counter(r.get("code", "?") for r in records)
    by_skill = Counter(r.get("skill", "?") for r in records)
    by_severity = Counter(r.get("severity", "?") for r in records)
    run_ids = sorted({r.get("run_id") for r in records if r.get("run_id")})
    run_id = run_ids[-1] if run_ids else datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    model_runtime = _model_provenance(records)
    summary = {
        "run_id": run_id,
        "git_sha": _git_sha(),
        "model": model_runtime["effective_model"],
        "model_source": model_runtime["effective_model_source"],
        "model_runtime": model_runtime,
        "appended_at": datetime.utcnow().isoformat() + "Z",
        "ndjson_source": str(ndjson_path),
        "total_findings": len(records),
        "by_severity": dict(by_severity),
        "by_code": dict(by_code),
        "by_skill_top10": dict(by_skill.most_common(10)),
        "n_skills_with_findings": len(by_skill),
    }

    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as h:
        h.write(json.dumps(summary) + "\n")

    print(f"Appended summary for run {run_id}:")
    print(f"  Total findings: {summary['total_findings']}")
    print(f"  By severity:    {summary['by_severity']}")
    print(f"  Top codes:      {dict(by_code.most_common(5))}")
    print(f"  History:        {HISTORY_PATH.relative_to(REPO_ROOT)}")
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
        print(f"Need ≥{last_n} history rows; have {len(rows)}.")
        return 1
    latest = rows[-1]
    prior = rows[-last_n]
    print(f"=== Diff: {prior.get('run_id')} → {latest.get('run_id')} ===")
    print(f"  Total findings: {prior['total_findings']} → {latest['total_findings']}"
          f" ({latest['total_findings'] - prior['total_findings']:+d})")

    prior_codes = prior.get("by_code", {})
    latest_codes = latest.get("by_code", {})

    new_codes = {c: n for c, n in latest_codes.items() if c not in prior_codes}
    gone_codes = {c: n for c, n in prior_codes.items() if c not in latest_codes}
    changed = {c: (prior_codes.get(c, 0), latest_codes.get(c, 0))
               for c in set(prior_codes) | set(latest_codes)
               if c in prior_codes and c in latest_codes
               and prior_codes[c] != latest_codes[c]}

    if new_codes:
        print("\nNew finding codes (regression alert):")
        for c, n in sorted(new_codes.items()):
            print(f"  {c}: {n} occurrence(s)")
    if gone_codes:
        print("\nResolved finding codes:")
        for c, n in sorted(gone_codes.items()):
            print(f"  {c}: was {n}, now 0")
    if changed:
        print("\nChanged code counts:")
        for c, (prior_n, latest_n) in sorted(changed.items()):
            arrow = "↑" if latest_n > prior_n else "↓"
            print(f"  {c}: {prior_n} → {latest_n} {arrow}")
    if not (new_codes or gone_codes or changed):
        print("\nNo per-code changes since prior run.")
    return 0


def summary(top_n):
    rows = _load_history()
    if not rows:
        print("No history yet. Run audit-skill --all --ndjson=run.ndjson, then "
              "audit_history.py append run.ndjson.")
        return 1
    print(f"=== History summary: {len(rows)} run(s) ===")

    # Repeat offenders: codes appearing in ≥N runs
    code_run_count = Counter()
    code_total_findings = Counter()
    for row in rows:
        for code, n in row.get("by_code", {}).items():
            code_run_count[code] += 1
            code_total_findings[code] += n
    print(f"\nRepeat-offender codes (top {top_n} by total findings across runs):")
    for code, total in code_total_findings.most_common(top_n):
        runs = code_run_count[code]
        print(f"  {code}: {total} total finding(s) across {runs} run(s) "
              f"({runs/len(rows):.0%} hit rate)")

    # Skill-level cumulative findings
    skill_totals = Counter()
    for row in rows:
        for skill, n in row.get("by_skill_top10", {}).items():
            skill_totals[skill] += n
    print(f"\nTop {top_n} skills by cumulative findings:")
    for skill, total in skill_totals.most_common(top_n):
        print(f"  {skill}: {total} finding(s)")

    # Trend
    totals = [r["total_findings"] for r in rows]
    if len(totals) >= 2:
        trend = totals[-1] - totals[0]
        direction = "↓ down" if trend < 0 else ("↑ up" if trend > 0 else "→ flat")
        print(f"\nTrend (first → latest): {totals[0]} → {totals[-1]}  ({direction} by {abs(trend)})")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub_append = sub.add_parser("append", help="Append a summary row from an NDJSON event log")
    sub_append.add_argument("ndjson", help="Path to NDJSON file emitted by audit-skill.py --ndjson")
    sub_diff = sub.add_parser("diff", help="Compare last two history rows")
    sub_diff.add_argument("--last", type=int, default=2, help="Compare against the N-th-most-recent run (default 2 = previous)")
    sub_summary = sub.add_parser("summary", help="Aggregate stats across all history rows")
    sub_summary.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    if args.cmd == "append":
        sys.exit(append(args.ndjson))
    elif args.cmd == "diff":
        sys.exit(diff(args.last))
    elif args.cmd == "summary":
        sys.exit(summary(args.top))


if __name__ == "__main__":
    main()
