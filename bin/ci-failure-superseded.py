#!/usr/bin/env python3
"""Decide whether a `main`-branch CI failure has been SUPERSEDED by later commits.

The /pr-fix stale-failure filter compares a failure against newer runs of the same
workflow. That is blind when NO newer run has completed — and on a repo whose rapid
pushes cancel in-flight CI, "latest completed run is a failure" stays true
indefinitely while the cause is long fixed in source.

Two factors, because neither alone is sufficient (both measured 2026-07-28):
  * recency  — a newer COMPLETED run of the same workflow that succeeded => DROP
  * supersession — how far `main` has advanced past the failing run's head sha

  mcp-infra   Terraform         ahead_by=20, no newer completed run -> SUPERSEDED
                                (the s3:PutInventoryConfiguration grant it failed
                                 on was already present in ci.tf)
  code-search Unit Tests        ahead_by=3,  newer runs green        -> SUPERSEDED
  mcp-servers Dependency Update ahead_by=1,  no newer run            -> CURRENT
                                (a genuine 12-minute-old failure whose sha already
                                 differed from HEAD — a bare sha-inequality test
                                 would have produced a false all-clear)

Verdicts: CURRENT | SUPERSEDED | DROP_SUCCEEDED | UNKNOWN
Exit 0 always (advisory); parse the verdict from stdout or use --json.
"""
import argparse
import json
import subprocess
import sys

SUPERSEDED_THRESHOLD = 3  # ahead_by >= this, with no newer completed run


def gh(args):
    p = subprocess.run(["gh"] + args, capture_output=True)
    return p.returncode, p.stdout.decode("utf-8", "replace").strip(), p.stderr.decode("utf-8", "replace")


def classify(ahead_by, newer_conclusion, threshold=SUPERSEDED_THRESHOLD):
    """Pure decision function — unit-testable without network.

    newer_conclusion: conclusion of the newest COMPLETED run of the same workflow
    on a NEWER sha, or None if there is none.
    """
    if newer_conclusion == "success":
        return "DROP_SUCCEEDED", "a newer completed run of this workflow succeeded"
    if ahead_by is None:
        return "UNKNOWN", "could not compare the failing sha against main"
    if ahead_by == 0:
        return "CURRENT", "the failing run's sha IS main HEAD"
    if ahead_by < threshold:
        return "CURRENT", (
            "main is only %d commit(s) ahead and this workflow has not re-run — "
            "normal churn, treat as current" % ahead_by
        )
    return "SUPERSEDED", (
        "main is %d commits ahead with no newer completed run of this workflow — "
        "READ THE SOURCE at current main for the specific fix before reporting "
        "this actionable" % ahead_by
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="org/repo")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    rc, out, err = gh(["run", "view", a.run_id, "--repo", a.repo,
                       "--json", "headSha,name,headBranch,conclusion,createdAt"])
    if rc != 0:
        print("UNKNOWN: cannot read run %s (%s)" % (a.run_id, err[:100]))
        return 0
    run = json.loads(out)
    sha, wf, branch = run["headSha"], run["name"], run["headBranch"]

    if branch != "main":
        print("CURRENT: branch is %r, not main — supersession check applies to main only"
              % branch)
        return 0

    rc, out, _ = gh(["api", "repos/%s/compare/%s...main" % (a.repo, sha), "--jq", ".ahead_by"])
    ahead = int(out) if (rc == 0 and out.isdigit()) else None

    # newest COMPLETED run of the same workflow on a different (newer) sha
    rc, out, _ = gh(["run", "list", "--repo", a.repo, "--branch", "main", "--limit", "40",
                     "--json", "name,conclusion,status,createdAt,headSha"])
    newer = None
    if rc == 0:
        try:
            runs = [r for r in json.loads(out)
                    if r.get("name") == wf and r.get("status") == "completed"
                    and r.get("conclusion") and r.get("createdAt", "") > run.get("createdAt", "")]
            runs.sort(key=lambda r: r["createdAt"], reverse=True)
            newer = runs[0]["conclusion"] if runs else None
        except Exception:
            newer = None

    verdict, why = classify(ahead, newer)
    if a.json:
        print(json.dumps({"verdict": verdict, "reason": why, "workflow": wf,
                          "ahead_by": ahead, "newer_completed": newer,
                          "sha": sha[:12]}, indent=2))
    else:
        print("%s: %s" % (verdict, why))
        print("  workflow=%s sha=%s ahead_by=%s newer_completed=%s"
              % (wf, sha[:12], ahead, newer))
    return 0


if __name__ == "__main__":
    sys.exit(main())
