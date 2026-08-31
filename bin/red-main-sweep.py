#!/usr/bin/env python3
"""Red-main sweeper — detect workflows whose LATEST completed run on a
repo's default branch is a failure, across the orgs we own.

WHY (2026-06-12 /pr-fix root-cause R1): three multi-week red mains went
unnoticed until a manual sweep — mcp-servers deploys (23 days), the OPA
bundle pipeline (18 days, production policy frozen), enforce-mirror
(13 days). Nothing watches for red mains; per-workflow Slack steps
demonstrably didn't close the gap (mcp-servers HAD one through its
23-day streak).

Design constraints (learned from those casualties):
- ZERO new provisioning. Uses the operator's existing `gh` CLI auth.
  No PAT (killed enforce-mirror), no webhook secret.
- Notifies through surfaces that already reach the operator daily:
  ~/.claude/red-mains.json consumed by the session-start banner, plus a
  macOS notification when reds exist.
- Instrument failures are LOUD and never masquerade as green
  (rules/security-review-before-pr.md, CI-gate proof line): a sweep that
  cannot read GitHub exits 2 and leaves the previous state file
  untouched; it does NOT write an empty "all green" state.

Scheduling: templates/launchd/com.example.red-main-sweep.plist (daily).
Manual run: python3 bin/red-main-sweep.py [--quiet]

Scope: orgs whose default-branch health is OURS to fix. Deliberately
excludes example-apps-org (other teams' repos; our touchpoints
there are PRs, which /pr-fix already discovers by involvement).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ORGS = ["example-org", "example-org", "example-labs-org"]
# CLAUDE_RED_MAINS_STATE overrides for tests — never write the real
# ~/.claude state from a test (the supergoal test-pollution class).
STATE_PATH = Path(os.environ.get("CLAUDE_RED_MAINS_STATE")
                  or Path.home() / ".claude" / "red-mains.json")
GH_TIMEOUT = 60

# Conclusions that mean "this workflow is currently red". `cancelled`,
# `skipped`, and `action_required` are excluded on purpose: a cancelled
# run (superseded by concurrency, manual stop) is not a broken main.
RED_CONCLUSIONS = {"failure", "timed_out", "startup_failure"}


def run_gh(args, timeout=GH_TIMEOUT):
    """Run a gh CLI command, return parsed JSON. Raises GhError on any
    failure — callers decide whether that is per-repo (tolerable, listed
    in the state file) or total (instrument failure, exit 2)."""
    proc = subprocess.run(
        ["gh", *args], capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        raise GhError(proc.stderr.decode("utf-8", "replace").strip()[:300])
    out = proc.stdout.decode("utf-8", "replace")
    return json.loads(out) if out.strip() else []


class GhError(RuntimeError):
    pass


def list_repos(org, gh=run_gh):
    rows = gh(["repo", "list", org, "--no-archived", "--limit", "200",
               "--json", "name,defaultBranchRef"])
    out = []
    for r in rows:
        branch = ((r.get("defaultBranchRef") or {}).get("name")) or "main"
        out.append((f"{org}/{r['name']}", branch))
    return out


def sweep_repo(repo, branch, gh=run_gh):
    """Return the list of red findings for one repo.

    Red = the most recent COMPLETED run of an ACTIVE workflow on the
    default branch concluded in RED_CONCLUSIONS. In-progress runs are
    ignored when picking "latest" — a fix in flight does not make the
    main green until it lands. Deleted/disabled workflows are excluded:
    their stale failure history is unfixable noise (live instance: a
    removed gitleaks caller workflow's last run stays 'failure' forever).
    """
    active = {
        w["name"] for w in gh(["workflow", "list", "-R", repo,
                               "--json", "name,state"])
        if w.get("state") == "active"
    }
    if not active:
        return []
    runs = gh(["run", "list", "-R", repo, "-b", branch, "--limit", "40",
               "--json", "workflowName,conclusion,status,createdAt,url"])
    latest_completed = {}
    for r in runs:  # newest first
        if r.get("status") != "completed":
            continue
        wf = r.get("workflowName") or "?"
        if wf not in latest_completed:
            latest_completed[wf] = r
    red = []
    for wf, r in sorted(latest_completed.items()):
        if wf in active and r.get("conclusion") in RED_CONCLUSIONS:
            red.append({
                "repo": repo,
                "workflow": wf,
                "conclusion": r.get("conclusion"),
                "last_run_at": r.get("createdAt"),
                "url": r.get("url"),
            })
    return red


def sweep(orgs=ORGS, gh=run_gh):
    """Sweep all orgs. Returns (red_findings, repo_errors, repos_swept).

    Raises GhError only when repo ENUMERATION fails for every org —
    that is an instrument failure (gh auth dead, network down), not a
    finding."""
    repos = []
    enum_errors = []
    for org in orgs:
        try:
            repos.extend(list_repos(org, gh=gh))
        except (GhError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            enum_errors.append(f"{org}: {e}")
    if not repos:
        raise GhError(
            "repo enumeration failed for every org — instrument failure, "
            "not an all-green sweep: " + "; ".join(enum_errors))

    red, errors = [], list(enum_errors)

    def one(item):
        repo, branch = item
        try:
            return sweep_repo(repo, branch, gh=gh), None
        except (GhError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            return [], f"{repo}: {e}"

    with ThreadPoolExecutor(max_workers=8) as ex:
        for findings, err in ex.map(one, repos):
            red.extend(findings)
            if err:
                errors.append(err)

    # >50% of repos unreadable = the sweep itself is broken; refuse to
    # publish a state file that under-reports.
    if len(errors) > len(repos) // 2:
        raise GhError(
            f"{len(errors)}/{len(repos)} repos unreadable — instrument "
            "failure: " + "; ".join(errors[:3]))
    return red, errors, len(repos)


def notify_macos(title, body):
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{body}" with title "{title}"'],
            capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        pass  # notification is best-effort; the state file is the record


def main(argv=None):
    argv = argv or sys.argv[1:]
    quiet = "--quiet" in argv
    try:
        red, errors, n_repos = sweep()
    except GhError as e:
        # Loud instrument failure: do NOT overwrite the previous state —
        # a broken sweep must never read as "all green".
        print(f"RED-MAIN-SWEEP: INSTRUMENT FAILURE — {e}", file=sys.stderr)
        return 2

    # Notification fires only for NEW reds vs the previous sweep —
    # standing reds live in the session-start banner; a daily "34 red
    # mains" notification is wallpaper within a week.
    prior_keys = set()
    if STATE_PATH.exists():
        try:
            prior = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            prior_keys = {(f["repo"], f["workflow"])
                          for f in prior.get("red", [])}
        except (json.JSONDecodeError, OSError, KeyError):
            pass
    new_red = [f for f in red if (f["repo"], f["workflow"]) not in prior_keys]

    state = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repos_swept": n_repos,
        "red": red,
        "errors": errors,
    }
    STATE_PATH.write_text(json.dumps(state, indent=1), encoding="utf-8")

    if red:
        summary = ", ".join(
            f"{f['repo'].split('/', 1)[1]}/{f['workflow']}" for f in red[:5])
        if len(red) > 5:
            summary += f" (+{len(red) - 5} more)"
        print(f"RED MAINS ({len(red)}, {len(new_red)} new): {summary}")
        if not quiet and new_red:
            new_summary = ", ".join(
                f"{f['repo'].split('/', 1)[1]}/{f['workflow']}"
                for f in new_red[:4])
            notify_macos(
                f"{len(new_red)} NEW red main workflow(s) "
                f"({len(red)} total)",
                new_summary[:180])
    else:
        print(f"all green ({n_repos} repos swept"
              + (f", {len(errors)} unreadable" if errors else "") + ")")
    if errors:
        for e in errors:
            print(f"  unreadable: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__ or "<usage TBD>"); sys.exit(0)
    sys.exit(main())
