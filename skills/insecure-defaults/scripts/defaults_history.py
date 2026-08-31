#!/usr/bin/env python3
"""insecure-defaults cross-report history — components 6 (memory) + 8 (observability).

Reads NDJSON event logs from `verify_defaults.py --ndjson PATH` and:

1. `append`  — summarize a report into `defaults-history.jsonl` (one row
   per scan: per-finding verdicts, fail-open vs fail-secure counts,
   pattern coverage). Reports accumulate so cross-scan trends emerge.

2. `diff`    — compare last two reports for the same codebase: did the
   fail-open count drop after a fix? Did a regression introduce a new
   `or "default"` shape?

3. `summary` — aggregate stats: which patterns recur, which env_vars
   appear repeatedly, which paths are repeat offenders.

Usage:
    defaults_history.py append <ndjson-path> [--repo NAME]
    defaults_history.py diff [--last N]
    defaults_history.py summary [--top N]
"""
import argparse, json, os, subprocess, sys
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HISTORY_PATH = REPO_ROOT / "skills" / "insecure-defaults" / "defaults-history.jsonl"


def _git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short=10", "HEAD"],
            cwd=REPO_ROOT, text=True, timeout=5,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return ""


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
        print(f"WARNING: {ndjson_path} contains no records", file=sys.stderr)

    by_finding = {}
    for r in records:
        fid = r.get("id")
        if not fid:
            continue
        by_finding.setdefault(fid, {"checks": {}, "verdicts": {}})
        by_finding[fid]["checks"][r.get("check", "?")] = bool(r.get("passed", True))
        if "verdict" in r:
            by_finding[fid]["verdicts"][r.get("check")] = r["verdict"]

    n_findings = len(by_finding)
    n_fail_open = sum(1 for f in by_finding.values()
                       if f["verdicts"].get("fail_open_classify") == "fail_open"
                       or f["verdicts"].get("startup_probe") == "fail_open")
    n_fail_secure = sum(1 for f in by_finding.values()
                         if f["verdicts"].get("fail_open_classify") == "fail_secure"
                         or f["verdicts"].get("startup_probe") == "fail_secure")
    run_ids = sorted({r.get("run_id") for r in records if r.get("run_id")})
    run_id = run_ids[-1] if run_ids else datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    summary = {
        "run_id": run_id,
        "repo": repo_override or "<unspecified>",
        "git_sha": _git_sha(),
        "model": os.environ.get("CLAUDE_MODEL", "unknown"),
        "appended_at": datetime.utcnow().isoformat() + "Z",
        "ndjson_source": str(ndjson_path),
        "n_findings": n_findings,
        "n_fail_open": n_fail_open,
        "n_fail_secure": n_fail_secure,
        "n_test_fixture": sum(1 for f in by_finding.values()
                               if not f["checks"].get("not_test_fixture", True)),
        "findings": list(by_finding.keys()),
    }

    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as h:
        h.write(json.dumps(summary) + "\n")

    print(f"Appended defaults report for repo={summary['repo']}, run {run_id}:")
    print(f"  Findings: {n_findings}")
    print(f"  Fail-open: {n_fail_open}, fail-secure: {n_fail_secure}")
    print(f"  Test-fixture filtered: {summary['n_test_fixture']}")
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
    repo_name = latest.get("repo")
    # Filter rows to match the latest row's repo to ensure same-codebase comparison
    same_repo_rows = [r for r in rows if r.get("repo") == repo_name]
    if len(same_repo_rows) < last_n:
        print(f"Need >={last_n} history rows for repo={repo_name}; have {len(same_repo_rows)}.")
        return 1
    prior = same_repo_rows[-last_n]
    print(f"=== Defaults diff: {prior.get('repo')}@{prior.get('run_id')} -> "
          f"{latest.get('repo')}@{latest.get('run_id')} ===")
    print(f"  Findings:    {prior.get('n_findings', 0)} -> {latest.get('n_findings', 0)}")
    print(f"  Fail-open:   {prior.get('n_fail_open', 0)} -> {latest.get('n_fail_open', 0)}"
          f" ({latest.get('n_fail_open', 0) - prior.get('n_fail_open', 0):+d})")
    print(f"  Fail-secure: {prior.get('n_fail_secure', 0)} -> {latest.get('n_fail_secure', 0)}")
    prior_ids = set(prior.get("findings", []))
    latest_ids = set(latest.get("findings", []))
    fixed = prior_ids - latest_ids
    new = latest_ids - prior_ids
    if fixed:
        print("\nFixed (gone from latest):")
        for fid in sorted(fixed):
            print(f"  {fid}")
    if new:
        print("\nNew (introduced since prior):")
        for fid in sorted(new):
            print(f"  {fid}")
    return 1 if new else 0


def summary(top_n):
    rows = _load_history()
    if not rows:
        print("No history yet. Run verify_defaults.py --ndjson=run.ndjson, then "
              "defaults_history.py append run.ndjson.")
        return 1
    print(f"=== Defaults-history summary: {len(rows)} report(s) ===")
    fid_count = Counter()
    for row in rows:
        for fid in row.get("findings", []):
            fid_count[fid] += 1
    print(f"\nMost recurrent finding IDs (top {top_n}):")
    for fid, n in fid_count.most_common(top_n):
        print(f"  {n}x  {fid}")
    repo_count = Counter(r.get("repo", "?") for r in rows)
    print(f"\nRepos scanned (top {top_n}):")
    for repo, n in repo_count.most_common(top_n):
        print(f"  {repo}: {n} report(s)")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub_append = sub.add_parser("append", help="Append a defaults-summary row from an NDJSON log")
    sub_append.add_argument("ndjson", help="Path to NDJSON file emitted by verify_defaults.py --ndjson")
    sub_append.add_argument("--repo", default=None, help="Repo label (otherwise <unspecified>)")
    sub_diff = sub.add_parser("diff", help="Compare last two reports")
    sub_diff.add_argument("--last", type=int, default=2)
    sub_sum = sub.add_parser("summary", help="Aggregate stats across all reports")
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
