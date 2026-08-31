#!/usr/bin/env python3
"""Shadow-replay `workflow_truth` over real workflow journals. READ-ONLY.

Purpose: prove the conservative aggregation rule reproduces the red-team-corrected
finding on the live corpus -- 2 false successes among 46 completed runs, with
killed runs reported SEPARATELY as valid terminal states rather than as defects.

Shadow means: compute and report only. Nothing is written to any journal, run
directory, or the live configuration.

Privacy: emits run IDs, states, counts, and reason strings only. It never prints a
result payload, transcript text, prompt, or file path outside the run-dir basename.

Usage:
    python3 bin/workflow_truth_replay.py                    # all local journals
    python3 bin/workflow_truth_replay.py --json out.json    # machine-readable
    python3 bin/workflow_truth_replay.py --root <dir>
    python3 bin/workflow_truth_replay.py --since 2026-07-12T08:31:55Z \\
                                        --until 2026-07-26T08:31:55Z
"""

from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from workflow_truth import (
    COMPLETED_PARTIAL,
    COMPLETED_SUCCESS,
    FAILED,
    KILLED,
    evaluate_journal_path,
)


def parse_iso(value: str) -> _dt.datetime:
    """Parse an ISO-8601 instant, accepting a trailing Z."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = _dt.datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt


def find_journals(root: str) -> list[str]:
    return sorted(glob.glob(os.path.join(root, "**", "journal.jsonl"), recursive=True))


def in_window(path: str, since, until) -> bool:
    """Half-open [since, until) filter on the journal's mtime.

    Half-open is deliberate: a closed interval double-counts an artifact sitting
    exactly on a boundary shared by two adjacent windows.
    """
    if since is None and until is None:
        return True
    try:
        mtime = _dt.datetime.fromtimestamp(
            os.path.getmtime(path), tz=_dt.timezone.utc
        )
    except OSError:
        return False
    if since is not None and mtime < since:
        return False
    if until is not None and mtime >= until:
        return False
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--root",
        default=os.path.expanduser("~/.claude"),
        help="directory to search for journal.jsonl (default: ~/.claude)",
    )
    ap.add_argument("--json", dest="json_out", help="write machine-readable results here")
    ap.add_argument("--since", help="ISO-8601 lower bound (inclusive)")
    ap.add_argument("--until", help="ISO-8601 upper bound (exclusive)")
    ap.add_argument(
        "--killed",
        default="",
        help="comma-separated run IDs known to have been killed",
    )
    args = ap.parse_args(argv)

    since = parse_iso(args.since) if args.since else None
    until = parse_iso(args.until) if args.until else None
    killed_ids = {x.strip() for x in args.killed.split(",") if x.strip()}

    journals = [p for p in find_journals(args.root) if in_window(p, since, until)]

    rows = []
    counts = {COMPLETED_SUCCESS: 0, COMPLETED_PARTIAL: 0, FAILED: 0, KILLED: 0}

    for path in journals:
        run_id = os.path.basename(os.path.dirname(path))
        truth = evaluate_journal_path(path, killed=(run_id in killed_ids))
        counts[truth.state] = counts.get(truth.state, 0) + 1
        rows.append(truth.to_dict())

    # A run whose journal evidence does not support success but which the
    # orchestrator would have reported as `completed`. This is the false-success
    # population, and `killed` is excluded because it never claimed success.
    would_be_false_success = [
        r for r in rows if r["state"] in (COMPLETED_PARTIAL, FAILED)
    ]
    eligible_completed = [r for r in rows if r["state"] != KILLED]

    print(f"journals evaluated: {len(rows)}")
    if since or until:
        print(f"window: [{args.since or '-inf'}, {args.until or '+inf'})  (half-open)")
    print("\n=== terminal-state distribution (states kept DISTINCT) ===")
    for state in (COMPLETED_SUCCESS, COMPLETED_PARTIAL, FAILED, KILLED):
        print(f"  {state}: {counts.get(state, 0)}")

    print("\n=== false-success population ===")
    print(f"  eligible (non-killed) runs: {len(eligible_completed)}")
    print(f"  runs whose evidence does NOT support a success claim: "
          f"{len(would_be_false_success)}")
    if eligible_completed:
        rate = len(would_be_false_success) / len(eligible_completed)
        print(f"  rate: {rate:.4f}")

    # Reason histogram tells us WHY, which is what drives the fix.
    hist: dict[str, int] = {}
    for r in rows:
        for reason in r["reasons"]:
            head = reason.split(";")[0].split("(")[0].strip()
            hist[head] = hist.get(head, 0) + 1
    print("\n=== reason histogram ===")
    for reason, n in sorted(hist.items(), key=lambda kv: -kv[1]):
        print(f"  {n:5d}  {reason}")

    total_children = sum(r["total_children"] for r in rows)
    total_missing = sum(r["missing_children"] for r in rows)
    total_error = sum(r["error_children"] for r in rows)
    print("\n=== child receipt coverage ===")
    print(f"  logical children: {total_children}")
    print(f"  missing receipts: {total_missing}")
    print(f"  error verdicts:   {total_error}")
    if total_children:
        print(f"  receipt coverage: "
              f"{(total_children - total_missing) / total_children:.4f}")

    if args.json_out:
        payload = {
            "generated_by": "bin/workflow_truth_replay.py",
            "window": {"since": args.since, "until": args.until, "bounds": "half-open"},
            "counts": counts,
            "eligible_completed": len(eligible_completed),
            "unsupported_success_claims": len(would_be_false_success),
            "runs": rows,
        }
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
        print(f"\nwrote {args.json_out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
