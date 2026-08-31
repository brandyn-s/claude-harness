#!/usr/bin/env python3
"""Detect rules that are hook-enforced but still show high violation
rates — candidates for demotion.

Phase 7b of the audit-rules lift. Joins two existing measurements:

  classify_rules.py: which rules are hook-enforced (decision: "block")
  scan_violations.py: per-rule session_rate_pct over the scan window

A rule that fires high session_rate despite being hook-enforced means
one of three things:

  1. Coverage gap — the hook fires on a narrower surface than the
     scanner detects (e.g., hook fires on .py writes, scanner detects
     in inline `python -c`). Fix: widen the hook.

  2. Agent workaround — agents work around the hook (use a different
     tool, encode the violation differently). Signal that the hook
     is annoying enough to drive avoidance behavior.

  3. Hook over-fires — hook blocks legitimate code, agents have to
     retry / rephrase. The retries inflate the apparent violation
     rate even though the hook is "working."

The detector emits a DEMOTE finding for each (hook-enforced, high-
rate) pair. Operators investigate to determine which subclass applies
and then choose: widen the hook (case 1), document operator workflow
(case 2), or actually demote to warn-mode (case 3).

The threshold (default 20%) signals a demotion candidate — rules that
are hook-enforced but show high session_rate suggest the hook either has
a coverage gap, is being worked around, or over-fires. See audit-rules/
SKILL.md "Demotion workflow" section for investigation guidance.

Rules with a DELIBERATE demotion recorded in AUDIT-TRACKERS/demotions.yaml
(surfaced via classify_rules.py --json `demotions`) are reported under
`already_demoted`, NOT as candidates — a decision the operator already made
is not an investigation item. 2026-08-22 incident: the encoding guard's
2026-06-27 platform demotion lived only in hook comments, so this detector
re-reported it as a three-hypothesis mystery every run.

Usage:
  detect_demotion_candidates.py
  detect_demotion_candidates.py --threshold 30 --json
  detect_demotion_candidates.py --days 30
  detect_demotion_candidates.py --scan-json /tmp/scan.json   # reuse a prior
      scan_violations.py --json output instead of re-scanning (faster, and
      keeps this report's numbers identical to the Step 1 scan's)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--threshold", type=float, default=20.0,
        help="session_rate_pct above which a hook-enforced rule is a "
             "demotion candidate (default 20.0)",
    )
    ap.add_argument(
        "--days", type=int, default=14,
        help="scan window in days",
    )
    ap.add_argument("--json", action="store_true",
                    help="emit JSON instead of human-readable text")
    ap.add_argument(
        "--scan-json", metavar="PATH",
        help="path to a prior scan_violations.py --json output to reuse "
             "instead of re-running the scanner (--days is ignored)",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    scanner = repo_root / "skills" / "audit-rules" / "references" / "scan_violations.py"
    classifier = repo_root / "skills" / "audit-rules" / "references" / "classify_rules.py"

    # Get classification
    r = subprocess.run(
        [sys.executable, str(classifier), "--json"],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        print(f"error: classify_rules failed: {r.stderr[:200]}", file=sys.stderr)
        return 1
    classification = json.loads(r.stdout)

    # Get scan — reuse a prior scan's JSON when provided so this report's
    # numbers match the Step 1 scan exactly (a re-scan drifts the window).
    if args.scan_json:
        try:
            scan = json.loads(
                Path(args.scan_json).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"error: cannot read --scan-json {args.scan_json}: {e}",
                  file=sys.stderr)
            return 1
    else:
        r = subprocess.run(
            [sys.executable, str(scanner), "--json", "--days", str(args.days)],
            capture_output=True, text=True, timeout=120,
        )
        if r.returncode != 0:
            print(f"error: scan_violations failed: {r.stderr[:200]}", file=sys.stderr)
            return 1
        scan = json.loads(r.stdout)

    violations = scan.get("violations", {})

    # Deliberate demotions (AUDIT-TRACKERS/demotions.yaml via classifier).
    # Only demotions effective on THIS platform exempt a rule — a win32-only
    # block gate demoted here may still be a genuine candidate on Windows.
    demoted_here = {
        d.get("scanner_rule"): d
        for d in classification.get("demotions", [])
        if d.get("effective_here")
    }

    # Join: classifier emits long-form rule descriptions keyed to
    # hook/skill source; scanner emits short identifiers. Map them
    # via the hook source filename — each scanner rule has a known
    # enforcing hook (per audit-rules/SKILL.md table).
    SCANNER_TO_HOOK = {
        "encoding-missing-open":      "post-write-edit.py",
        "missing-stdout-reconfigure": "post-write-edit.py",
        "inline-python-c":            "post-write-edit.py",
        "str-replace-crlf-risk":      "post-write-edit.py",
        "git-commit-no-branch-check": "bash-security-guard.py",
        # websearch-webfetch-used has no hook (prompt-only); included for
        # completeness — will never appear in hook_sources, so it's
        # correctly excluded from demotion candidates.
    }
    rules_classifications = classification.get("rules", [])
    hook_sources_enforced = {
        r.get("source", "") for r in rules_classifications
        if "hook-enforced" in str(r.get("layer", "")).lower()
    }

    candidates = []
    already_demoted = []
    for rule, v in violations.items():
        rate = v.get("session_rate_pct", 0)
        if rate < args.threshold:
            continue
        demotion = demoted_here.get(rule)
        if demotion:
            already_demoted.append({
                "rule": rule,
                "session_rate_pct": rate,
                "hook_source": demotion.get("hook"),
                "demoted_on": demotion.get("date"),
                "demotion_pr": demotion.get("pr"),
                "rationale": demotion.get("rationale"),
                "note": (
                    "deliberately demoted (AUDIT-TRACKERS/demotions.yaml) — "
                    "not a candidate; re-promote only with evidence that "
                    "overturns the recorded rationale"
                ),
            })
            continue
        hook = SCANNER_TO_HOOK.get(rule)
        if not hook or hook not in hook_sources_enforced:
            continue
        candidates.append({
            "rule": rule,
            "session_rate_pct": rate,
            "hook_source": hook,
            "defense_layer": "hook-enforced",
            "threshold": args.threshold,
            "unique_sessions": v.get("unique_sessions", 0),
            "count": v.get("count", 0),
            "hypothesis": (
                "high rate despite hook enforcement — either coverage gap "
                "(hook fires on narrower surface than scanner detects), "
                "agent workaround (agents avoid the hook by encoding "
                "differently), or hook over-fires (driving retries that "
                "inflate the count)"
            ),
        })

    if args.json:
        print(json.dumps({
            "demotion_candidates": candidates,
            "already_demoted": already_demoted,
            "threshold_pct": args.threshold,
            "scan_window_days": None if args.scan_json else args.days,
            "scan_source": args.scan_json or "live scan",
            "scan_window": scan.get("scan_window"),
            "total_hook_enforced_rules": len(hook_sources_enforced),
        }, indent=2))
    else:
        for d in already_demoted:
            print(
                f"already demoted (not a candidate): {d['rule']} "
                f"at {d['session_rate_pct']}% — demoted {d['demoted_on']} "
                f"(PR #{d['demotion_pr']}): {d['rationale']}"
            )
        if already_demoted:
            print()
        if not candidates:
            window = (
                f"scan {args.scan_json}" if args.scan_json
                else f"{args.days}d window"
            )
            print(
                f"No demotion candidates found (threshold "
                f"{args.threshold}% over {window})."
            )
            return 0
        print(f"Demotion candidates (rate >= {args.threshold}% AND hook-enforced):")
        print()
        for c in candidates:
            print(f"  {c['rule']}:")
            print(f"    session_rate_pct: {c['session_rate_pct']}%")
            print(f"    defense_layer:    {c['defense_layer']}")
            print(f"    sessions:         {c['unique_sessions']}")
            print(f"    count:            {c['count']}")
            print(f"    hypothesis:       {c['hypothesis']}")
            print()
        print(
            "Per audit-rules/SKILL.md 'Demotion workflow': investigate each "
            "candidate to determine if hook needs widening, operator workflow "
            "needs documenting, or hook should be demoted to warn-mode."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
