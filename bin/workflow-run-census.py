#!/usr/bin/env python3
"""Workflow-run census — per-conclusion run totals from the API's OWN counts,
with an explicit unaccounted residual. Answers "has this workflow EVER
succeeded, and what is its lifetime conclusion distribution?"

WHY THIS EXISTS — three friction events on misreading `gh run` conclusion
shapes, each of which a note failed to prevent:

  1. 2026-08-25 — a status formatter filtered
     `conclusion not in ("success","skipped",None)` and reported 16 FAILED
     steps on a healthy run, because a pending step's conclusion is the empty
     STRING, not None.
  2. 2026-08-25 — step conclusions read from an in-progress run showed `Post
     Run *` teardown steps as failed; querying each job after completion
     showed SUCCESS.
  3. 2026-08-26 — a workflow-health sweep derived failures as
     `total - success`, which buckets healthy SKIPPED runs as failures. It
     produced a false "never succeeded" finding against another team's
     workflow and inflated the affected class from 1 workflow to 2.

All three are one class: a conclusion is misread because the reading was
DERIVED rather than counted. The durable form of that lesson is a predicate,
not prose (knowledge-base `self-verifying-documentation`), so this tool
counts every bucket explicitly and NEVER subtracts.

SCOPE — this is deliberately NOT a red-main detector. `bin/red-main-sweep.py`
already answers "is the LATEST completed run on the default branch red?" and
already gets the two hard parts right (it skips `status != "completed"`, and
excludes `skipped`/`cancelled` from its red set). It cannot answer a HISTORY
question: it reads a 40-run page, so it has no totals, no first/last
occurrence, and no way to say "this lane has never once been green." That gap
is what this fills. Do not duplicate red-main-sweep's job here.

INTERRUPTION: safe — read-only. No state file, no writes, no mutation. A kill
mid-run loses only the in-progress report.

Usage:
    python3 bin/workflow-run-census.py --repo <org/repo>
    python3 bin/workflow-run-census.py --repo <org/repo> --all-workflows
    python3 bin/workflow-run-census.py --repo <org/repo> --workflow "Validate Config"
    python3 bin/workflow-run-census.py --repo <org/repo> --branch main --json

Exit codes: 0 = census produced; 2 = instrument failure (nothing trustworthy
to report); 3 = census produced but its own coverage check FAILED, so the
counts must not be cited.

ON EXIT 3, RE-RUN BEFORE DIAGNOSING. A coverage failure has two causes and
only one is a code defect. Measured 2026-08-27 on this repo's own "Validate
Config" workflow: immediately after ~420 rapid API calls, one bucket call
returned success=1479 against an unfiltered total of 5873, leaving 3,638 runs
unaccounted. Two consecutive re-runs returned success=5116 with a residual of
1, matching an independent direct probe. So the API can transiently
UNDER-REPORT a total_count under load, and the residual catches that too —
not just a stale bucket enum. The tool refused to publish the bad number
rather than reporting 1,479 successes as a finding, which is the whole point
of counting against the unfiltered total. Reproduce before believing either
outcome.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

GH_TIMEOUT = 60

# The documented allowed values for the `status` query parameter on
# GET /repos/{owner}/{repo}/actions/runs, verified against
# docs.github.com/en/rest/actions/workflow-runs (apiVersion 2022-11-28,
# fetched 2026-08-27). The doc's own wording: "Returns workflow runs with the
# check run status OR CONCLUSION that you specify."
#
# `completed` is deliberately EXCLUDED from this list even though it is a
# documented value: it is a STATUS that every terminal conclusion also
# satisfies, so including it would double-count most of the population and
# make the residual meaningless.
#
# `startup_failure` IS here even though the doc above does NOT list it. That
# is a documentation gap, not a filter gap, and it was settled by measurement
# rather than by reading: an unsupported filter value returns 0 instead of an
# error, so a 0 alone could not distinguish "none" from "unsupported". The
# discriminator is a KNOWN-POSITIVE. Measured 2026-08-27 on
# example-org/.github "PR Security Review (Required)" (id 240640988): an
# exhaustive 297-run walk found exactly 9 runs with conclusion
# `startup_failure`, and `status=startup_failure` returned 9 while a
# deliberately invalid `status=__control_invalid__` returned 0. So the filter
# works and the docs are incomplete.
#
# This was found BY the residual check below: excluding startup_failure left 9
# of 297 runs unaccounted, which tripped the coverage warning instead of
# silently under-reporting. Anything the enum still cannot see behaves the
# same way — it lands in the residual, which is where an unreadable
# population belongs.
BUCKETS = (
    "success",
    "failure",
    "startup_failure",
    "skipped",
    "cancelled",
    "neutral",
    "timed_out",
    "action_required",
    "stale",
    "in_progress",
    "queued",
    "requested",
    "waiting",
    "pending",
)

#: Conclusions that mean the run did not do its job. Kept separate from
#: BUCKETS so that adding a bucket never silently changes the verdict, and
#: aligned with bin/red-main-sweep.py's RED_CONCLUSIONS. `cancelled` and
#: `skipped` are NOT failures: a cancelled run was superseded, and a skipped
#: run is a path filter or an `if:` guard correctly declining.
#: `startup_failure` IS a failure — the workflow file never parsed or its
#: reusable target was unreachable, so a lane with only startup_failures has
#: never once succeeded and must not read as NO-TERMINAL-RUNS.
FAILING = ("failure", "timed_out", "action_required", "startup_failure")

#: In-flight statuses. A run here has no conclusion yet; its conclusion field
#: is the empty STRING, not None (friction event 1 above).
IN_FLIGHT = ("in_progress", "queued", "requested", "waiting", "pending")


class GhError(RuntimeError):
    """A gh invocation failed, or returned something that is not a count."""


def run_gh_count(path, gh_runner=None):
    """Return the API's own `total_count` for a runs query.

    Uses `gh api --jq` so the count is extracted SERVER-SIDE: piping a raw
    body into jq fails on control characters in commit messages, and `gh api`
    writes its error JSON to STDOUT rather than stderr, so a 404 body would
    otherwise be captured as if it were output.
    """
    runner = gh_runner or _default_runner
    out = runner(["api", path, "--jq", ".total_count"])
    text = (out or "").strip()
    if not text:
        raise GhError(f"empty count for {path}")
    # A gh error body lands on stdout; it is never a bare integer.
    try:
        return int(text)
    except ValueError as exc:
        raise GhError(f"non-numeric count for {path}: {text[:200]}") from exc


def _default_runner(args, timeout=GH_TIMEOUT):
    proc = subprocess.run(["gh", *args], capture_output=True, timeout=timeout)
    out = proc.stdout.decode("utf-8", "replace")
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        raise GhError((err or out).strip()[:300])
    return out


def _query(repo, workflow_id=None, branch=None, status=None, page=None,
           per_page=1):
    base = (f"repos/{repo}/actions/workflows/{workflow_id}/runs"
            if workflow_id else f"repos/{repo}/actions/runs")
    params = [f"per_page={per_page}"]
    if branch:
        params.append(f"branch={branch}")
    if status:
        params.append(f"status={status}")
    if page:
        params.append(f"page={page}")
    return f"{base}?" + "&".join(params)


def coverage(total, counts, in_flight_slack=None):
    """Grade the census against its own arithmetic.

    Returns (residual, ok, reason). `residual` is the population the bucket
    enum could not see. It is REPORTED, never attributed to a conclusion —
    that attribution is the bug this tool exists to prevent.

    A small residual is expected and benign: the unfiltered total and the
    per-bucket counts are separate API calls, so runs that start or finish
    between them shift the arithmetic by a few. The tolerance is therefore
    derived from the observed in-flight population rather than being a round
    guess, with a floor for the case where nothing is in flight.
    """
    accounted = sum(counts.get(b, 0) for b in BUCKETS)
    residual = total - accounted
    if in_flight_slack is None:
        in_flight_slack = sum(counts.get(b, 0) for b in IN_FLIGHT)
    # Floor of 2: two separate calls can each straddle one run transition.
    tolerance = max(2, in_flight_slack * 2)
    if residual < 0:
        return residual, False, (
            f"buckets sum to MORE than the unfiltered total ({accounted} > "
            f"{total}) — a bucket is double-counting; treat every count as "
            "unusable")
    if residual > tolerance:
        return residual, False, (
            f"{residual} of {total} runs fall outside the bucket enum "
            f"(tolerance {tolerance}) — the enum is incomplete or GitHub "
            "added a conclusion; counts are NOT a census")
    return residual, True, ""


def verdict(counts):
    """Classify a workflow from counted buckets only.

    BORN-BROKEN is the finding red-main-sweep cannot produce: zero successes
    ever, alongside real failures. It needs no bisect — there is no last-good
    commit to find.
    """
    success = counts.get("success", 0)
    failing = sum(counts.get(b, 0) for b in FAILING)
    terminal = success + failing + sum(
        counts.get(b, 0) for b in ("skipped", "cancelled", "neutral", "stale"))
    if terminal == 0:
        return "NO-TERMINAL-RUNS"
    if success == 0 and failing > 0:
        return "BORN-BROKEN"
    if failing == 0:
        return "CLEAN"
    return "MIXED"


def census_one(repo, workflow_id=None, workflow_name=None, branch=None,
               gh_runner=None):
    """Count every bucket for one workflow (or the whole repo)."""
    total = run_gh_count(_query(repo, workflow_id, branch), gh_runner)
    counts = {}
    for bucket in BUCKETS:
        counts[bucket] = run_gh_count(
            _query(repo, workflow_id, branch, status=bucket), gh_runner)
    residual, ok, reason = coverage(total, counts)
    row = {
        "workflow": workflow_name or "(all workflows)",
        "workflow_id": workflow_id,
        "total": total,
        "counts": counts,
        "residual_unaccounted": residual,
        "coverage_ok": ok,
        "verdict": verdict(counts),
    }
    if not ok:
        row["coverage_problem"] = reason
    if counts.get("failure", 0) > 0:
        row["failure_first_at"], row["failure_last_at"] = failure_span(
            repo, counts["failure"], workflow_id, branch, gh_runner)
    return row


def failure_span(repo, failure_total, workflow_id=None, branch=None,
                 gh_runner=None):
    """(oldest, newest) failure timestamps.

    A lookback total alone cannot distinguish an ACTIVE problem from closed
    history; the first and last occurrence are what separate them. The oldest
    is reached by asking for the LAST page at per_page=1 — the API's own
    pagination, not a local scan.
    """
    runner = gh_runner or _default_runner

    def created_at(page):
        out = runner(["api", _query(repo, workflow_id, branch,
                                    status="failure", page=page),
                      "--jq", ".workflow_runs[0].created_at // empty"])
        return (out or "").strip() or None

    newest = created_at(1)
    oldest = created_at(failure_total) if failure_total > 1 else newest
    return oldest, newest


def list_workflows(repo, gh_runner=None):
    """Active AND disabled workflows, with id/name/state.

    Disabled ones are included on purpose: this tool answers a history
    question, and "this lane never worked and is now switched off" is a
    finding, not noise. The caller decides what to do with the state.
    """
    runner = gh_runner or _default_runner
    out = runner(["api", f"repos/{repo}/actions/workflows?per_page=100",
                  "--jq", ".workflows[] | [.id, .state, .name] | @tsv"])
    rows = []
    for line in (out or "").splitlines():
        parts = line.rstrip("\n").split("\t")
        if len(parts) >= 3 and parts[0].strip().isdigit():
            rows.append({"id": int(parts[0]), "state": parts[1],
                         "name": "\t".join(parts[2:])})
    return rows


def render(report):
    lines = []
    repo = report["repo"]
    scope = f" branch={report['branch']}" if report.get("branch") else ""
    lines.append(f"workflow-run census: {repo}{scope}")
    for row in report["rows"]:
        c = row["counts"]
        lines.append("")
        state = f" [{row['state']}]" if row.get("state") else ""
        lines.append(f"  {row['workflow']}{state}")
        lines.append(f"    verdict        : {row['verdict']}")
        lines.append(f"    total (API)    : {row['total']}")
        counted = "  ".join(
            f"{b}={c[b]}" for b in BUCKETS if c.get(b))
        lines.append(f"    counted        : {counted or '(none)'}")
        lines.append(f"    unaccounted    : {row['residual_unaccounted']}"
                     + ("" if row["coverage_ok"] else "   <-- SEE WARNING"))
        if row.get("failure_first_at"):
            lines.append(f"    failures span  : {row['failure_first_at']}"
                         f" .. {row['failure_last_at']}")
        if not row["coverage_ok"]:
            lines.append(f"    WARNING: {row['coverage_problem']}")
    born = [r["workflow"] for r in report["rows"]
            if r["verdict"] == "BORN-BROKEN"]
    if born:
        lines.append("")
        lines.append(f"BORN-BROKEN ({len(born)}): " + ", ".join(born))
        lines.append("  Zero successes ever. There is no last-good commit, "
                     "so do not bisect.")
    if report.get("errors"):
        lines.append("")
        for e in report["errors"]:
            lines.append(f"  unreadable: {e}")
    return "\n".join(lines)


def build_report(repo, branch=None, all_workflows=False, workflow=None,
                 gh_runner=None):
    rows, errors = [], []
    if all_workflows or workflow:
        try:
            found = list_workflows(repo, gh_runner)
        except (GhError, subprocess.TimeoutExpired) as exc:
            raise GhError(f"cannot list workflows for {repo}: {exc}") from exc
        if workflow:
            needle = workflow.casefold()
            found = [w for w in found
                     if needle in w["name"].casefold()
                     or str(w["id"]) == workflow]
            if not found:
                raise GhError(
                    f"no workflow in {repo} matches {workflow!r} — "
                    "an empty match is not an empty census")

        def one(wf):
            try:
                row = census_one(repo, wf["id"], wf["name"], branch, gh_runner)
                row["state"] = wf["state"]
                return row, None
            except (GhError, subprocess.TimeoutExpired) as exc:
                return None, f"{wf['name']}: {exc}"

        with ThreadPoolExecutor(max_workers=6) as pool:
            for row, err in pool.map(one, found):
                if row:
                    rows.append(row)
                if err:
                    errors.append(err)
        rows.sort(key=lambda r: r["workflow"])
        if found and not rows:
            raise GhError(
                f"all {len(found)} workflows unreadable — instrument "
                "failure, not an empty census: " + "; ".join(errors[:3]))
    else:
        rows.append(census_one(repo, None, None, branch, gh_runner))
    return {"repo": repo, "branch": branch, "rows": rows, "errors": errors}


def build_parser():
    p = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", required=True, metavar="OWNER/REPO")
    p.add_argument("--branch")
    p.add_argument("--workflow",
                   help="name substring or numeric id; matching is required "
                        "to find something")
    p.add_argument("--all-workflows", action="store_true",
                   help="per-workflow breakdown instead of a repo total")
    p.add_argument("--json", action="store_true")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        report = build_report(args.repo, args.branch, args.all_workflows,
                              args.workflow)
    except (GhError, subprocess.TimeoutExpired) as exc:
        print(f"workflow-run-census: INSTRUMENT FAILURE — {exc}",
              file=sys.stderr)
        return 2
    print(json.dumps(report, indent=1) if args.json else render(report))
    if any(not r["coverage_ok"] for r in report["rows"]):
        print("workflow-run-census: coverage check FAILED — counts above are "
              "not a census; do not cite them", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
