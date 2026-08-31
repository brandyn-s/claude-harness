#!/usr/bin/env python3
"""threat-model cross-model history — components 6 (memory) + 8 (observability).

Reads NDJSON event logs from `verify_claims.py --ndjson PATH` and:

1. `append`  — summarize a threat-model verification into
   `model-history.jsonl`. One row per repo per run: structure pass/fail,
   file-ref resolution count, surface attribution stats, n claims
   verified vs unverified.

2. `diff`    — compare last two runs for the same repo. Did the new
   model add surfaces? Did file-ref breakage creep in?

3. `summary` — aggregate stats: which claim kinds have the highest
   unverified rate, which repos have the most surfaces, average
   file-ref resolution success.

Usage:
    model_history.py append <ndjson-path> [--repo NAME]
    model_history.py diff [--last N]
    model_history.py summary [--top N]
"""
import argparse, json, os, subprocess, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HISTORY_PATH = REPO_ROOT / "skills" / "threat-model" / "model-history.jsonl"


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


def append(ndjson_path, repo_override):
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
        print(f"ERROR: no valid NDJSON records in {ndjson_path}", file=sys.stderr)
        print("hint: pass the event log emitted by verify_claims.py --ndjson PATH",
              file=sys.stderr)
        return 2

    by_check = {}
    for r in records:
        check = r.get("check", "?")
        if check not in by_check:
            by_check[check] = True
        if not r.get("passed", True):
            by_check[check] = False

    n_refs = next((r.get("n_refs", 0) for r in records if r.get("check") == "file_refs_resolve"), 0)
    n_missing = next((r.get("n_missing", 0) for r in records if r.get("check") == "file_refs_resolve"), 0)
    n_surfaces = next((r.get("n_surfaces", 0) for r in records if r.get("check") == "surface_attribution"), 0)
    n_claim_intents = sum(1 for r in records if r.get("check") == "calls_edge_intent")
    n_claims_verified = sum(1 for r in records if r.get("check") == "calls_edge_grounding" and r.get("verdict") == "GROUNDED")
    n_claims_unverified = sum(1 for r in records if r.get("check") == "calls_edge_grounding" and r.get("verdict") == "UNSUBSTANTIATED")
    run_ids = sorted({r.get("run_id") for r in records if r.get("run_id")})
    run_id = run_ids[-1] if run_ids else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    model_runtime = _model_provenance(records)
    summary = {
        "run_id": run_id,
        "repo": repo_override or "<unspecified>",
        "git_sha": _git_sha(),
        "model": model_runtime["effective_model"],
        "model_source": model_runtime["effective_model_source"],
        "model_runtime": model_runtime,
        "appended_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "ndjson_source": str(ndjson_path),
        "checks": by_check,
        "n_refs": n_refs,
        "n_missing_refs": n_missing,
        "n_surfaces": n_surfaces,
        "n_claim_intents": n_claim_intents,
        "n_claims_verified": n_claims_verified,
        "n_claims_unverified": n_claims_unverified,
    }

    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as h:
        h.write(json.dumps(summary) + "\n")

    print(f"Appended threat-model summary for repo={summary['repo']}, run {run_id}:")
    print(f"  Surfaces: {n_surfaces}, refs: {n_refs} ({n_missing} missing)")
    print(f"  Claims: {n_claim_intents} intents, {n_claims_verified} verified, {n_claims_unverified} unverified")
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
    print(f"=== Threat-model diff: {prior.get('repo')}@{prior.get('run_id')} -> "
          f"{latest.get('repo')}@{latest.get('run_id')} ===")
    print(f"  Surfaces:        {prior.get('n_surfaces', 0)} -> {latest.get('n_surfaces', 0)}"
          f" ({latest.get('n_surfaces', 0) - prior.get('n_surfaces', 0):+d})")
    print(f"  Refs (missing):  {prior.get('n_missing_refs', 0)} -> {latest.get('n_missing_refs', 0)}"
          f" ({latest.get('n_missing_refs', 0) - prior.get('n_missing_refs', 0):+d})")
    print(f"  Claims verified: {prior.get('n_claims_verified', 0)} -> {latest.get('n_claims_verified', 0)}")
    return 0


def summary(top_n):
    rows = _load_history()
    if not rows:
        print("No history yet. Run verify_claims.py --ndjson=run.ndjson, then "
              "model_history.py append run.ndjson.")
        return 1
    print(f"=== Threat-model history summary: {len(rows)} model(s) ===")
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
    repo_count = Counter(r.get("repo", "?") for r in rows)
    print(f"\nRepos modeled (top {top_n}):")
    for repo, n in repo_count.most_common(top_n):
        print(f"  {repo}: {n} model(s)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub_append = sub.add_parser("append", help="Append a model-summary row from NDJSON")
    sub_append.add_argument("ndjson", help="Path to NDJSON file emitted by verify_claims.py --ndjson")
    sub_append.add_argument("--repo", default=None, help="Repo label")
    sub_diff = sub.add_parser("diff", help="Compare last two models")
    sub_diff.add_argument("--last", type=int, default=2)
    sub_sum = sub.add_parser("summary", help="Aggregate stats across all models")
    sub_sum.add_argument("--top", type=int, default=10)
    args = ap.parse_args()
    if args.cmd == "append":
        sys.exit(append(args.ndjson, args.repo))
    elif args.cmd == "diff":
        sys.exit(diff(args.last))
    elif args.cmd == "summary":
        sys.exit(summary(args.top))


if __name__ == "__main__":
    main()
