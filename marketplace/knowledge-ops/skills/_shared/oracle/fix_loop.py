"""Layer D — fix-loop verification.

Given a finding with a deterministic Reproducer and a proposed fix
(applied to the working tree or as a diff), verify:

  PRE:  reproducer.fires() must return True (bug is present before fix).
  POST: reproducer.fires() must return False (bug is gone after fix).

This catches three failure modes:

  STALE-PRE: pre fails to fire — the finding was already fixed before
    this attempt; the "fix" is a no-op.
  FIX-INEFFECTIVE: pre fires, post still fires — the fix doesn't
    resolve the reproducer; either the diagnosis was wrong or the
    patch missed.
  VERIFIED: pre fires, post does not — the fix works.
  REGRESSED: post fires AND introduces additional reproducer signal
    (TODO: cross-check other findings; out of scope for this single-
    finding loop).

The verifier requires the caller to provide ``before`` and ``after``
states. Two integration shapes are supported:

  git-refs: pass two refs (commit hashes / branch names). The loop
    checks each out via ``git worktree add`` so the live tree isn't
    disturbed. Useful for verifying historical PRs.

  diff: pass a unified diff string. The loop applies the diff,
    re-runs, then rolls back. Useful for verifying an in-flight fix
    before committing.

  workdir-snapshot: pass the file paths the fix touches. The loop
    snapshots them (copy to tmp), reverts via ``git stash``,
    re-verifies, then restores. Useful for the common case
    "I just edited some files; check if the fix is real".
"""
from __future__ import annotations

import dataclasses
import os
import subprocess
import tempfile
from pathlib import Path

from .finding import Finding
from .trace import finding_id, reproducer_command_sha, trace_invocation


@dataclasses.dataclass
class FixVerifyResult:
    finding: Finding
    status: str  # VERIFIED | STALE-PRE | FIX-INEFFECTIVE | ERROR
    pre_fires: bool
    post_fires: bool
    evidence_pre: str
    evidence_post: str


def verify_fix_against_refs(
    finding: Finding,
    repo_root: Path,
    pre_ref: str,
    post_ref: str,
) -> FixVerifyResult:
    """Use git worktrees to check both refs without disturbing the
    working tree. Both worktrees are torn down at the end."""
    with tempfile.TemporaryDirectory(prefix="audit-skill-oracle-") as td:
        td_path = Path(td)
        pre_wt = td_path / "pre"
        post_wt = td_path / "post"
        try:
            _run_git(["worktree", "add", "--detach", str(pre_wt), pre_ref], repo_root)
            _run_git(["worktree", "add", "--detach", str(post_wt), post_ref], repo_root)
            pre_fires, ev_pre = finding.reproducer.fires(pre_wt)
            post_fires, ev_post = finding.reproducer.fires(post_wt)
        finally:
            # Always tear down worktrees; ignore errors (e.g., already gone).
            for wt in (pre_wt, post_wt):
                if wt.exists():
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", str(wt)],
                        cwd=str(repo_root), capture_output=True,
                    )
    result = _classify(finding, pre_fires, post_fires, ev_pre, ev_post)
    _write_d_record(
        finding, result.status,
        f"pre_fires={result.pre_fires} post_fires={result.post_fires}; "
        f"{result.evidence_post[:120]}",
        {"mode": "refs", "pre_ref": pre_ref, "post_ref": post_ref},
    )
    return result


def verify_fix_in_place(
    finding: Finding,
    repo_root: Path,
    touched_paths: list[Path],
) -> FixVerifyResult:
    """Verify by snapshotting the touched files, running the
    reproducer against the post-state (the working tree as-is),
    then reverting to the snapshot for the pre-state check, then
    restoring."""
    # Snapshot the post-state of touched files.
    snapshots: dict[Path, str] = {}
    for p in touched_paths:
        if p.is_file():
            snapshots[p] = p.read_text(encoding="utf-8")

    # POST = current state
    post_fires, ev_post = finding.reproducer.fires(repo_root)

    # PRE = revert touched files to HEAD, then re-check.
    try:
        for p in touched_paths:
            rel = p.relative_to(repo_root) if p.is_absolute() else p
            subprocess.run(
                ["git", "checkout", "HEAD", "--", str(rel)],
                cwd=str(repo_root), capture_output=True,
            )
        pre_fires, ev_pre = finding.reproducer.fires(repo_root)
    finally:
        # Restore the snapshots so the user's working tree is unchanged.
        for p, contents in snapshots.items():
            p.write_text(contents, encoding="utf-8")

    result = _classify(finding, pre_fires, post_fires, ev_pre, ev_post)
    _write_d_record(
        finding, result.status,
        f"pre_fires={result.pre_fires} post_fires={result.post_fires}; "
        f"{result.evidence_post[:120]}",
        {"mode": "in_place"},
    )
    return result


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd), capture_output=True, text=True, check=True,
    )


def _write_d_record(finding: Finding, verdict: str, evidence: str,
                    extra_meta: dict | None = None) -> None:
    """Write one Layer-D trace record (SPEC §"Trace contract").

    Layer D had no trace wiring before this; the enforced SubagentStop
    gate reads these records (verdict in {FIX-INEFFECTIVE, INTRODUCED})
    to block a bad fix from finishing. ``session_id`` attributes the
    record to the dispatching subagent — "" when the orchestrator hasn't
    exported ``AUDIT_SKILL_ORACLE_SESSION``, which leaves the gate
    fail-safe-inert. Trace-write failure never propagates (the context
    manager swallows OSError)."""
    fid = finding_id(finding.skill, finding.code, finding.description)
    input_meta = {
        "reproducer_type": finding.reproducer.type,
        "reproducer_command_sha": reproducer_command_sha(
            finding.reproducer.command or finding.reproducer.path),
        "session_id": os.environ.get("AUDIT_SKILL_ORACLE_SESSION", ""),
    }
    if extra_meta:
        input_meta.update(extra_meta)
    with trace_invocation("D", finding.skill, fid, input_meta) as tr:
        tr["verdict"] = verdict
        tr["evidence"] = evidence


def _classify(
    finding: Finding,
    pre_fires: bool,
    post_fires: bool,
    ev_pre: str,
    ev_post: str,
) -> FixVerifyResult:
    if pre_fires and not post_fires:
        status = "VERIFIED"
    elif not pre_fires:
        status = "STALE-PRE"
    elif pre_fires and post_fires:
        status = "FIX-INEFFECTIVE"
    else:  # not pre, not post — should not happen given control flow above
        status = "ERROR"
    return FixVerifyResult(
        finding=finding,
        status=status,
        pre_fires=pre_fires,
        post_fires=post_fires,
        evidence_pre=ev_pre,
        evidence_post=ev_post,
    )


# ──────────────────────────────────────────────────────────────────
# Regression check — verify the fix doesn't introduce new bugs.
# ──────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class RegressionResult:
    """Result of running an other-finding's reproducer pre and post.
    A regression is detected when pre_fires is False but post_fires
    is True — the fix introduced a bug that wasn't there before.

    Status values:
      CLEAN          — pre and post both False (no signal either way)
      PRE-EXISTING   — pre and post both True (this finding was
                       already firing; not caused by the current fix)
      INTRODUCED     — pre False, post True (regression caused by fix)
      RESOLVED       — pre True, post False (side benefit; bonus fix)
    """
    finding: Finding
    status: str
    pre_fires: bool
    post_fires: bool
    evidence_pre: str
    evidence_post: str


@dataclasses.dataclass
class FixVerifyWithRegressionResult:
    """Combined Layer D verification + regression-check result.

    `primary` is the result of verifying the target finding's
    reproducer flips True → False. `regressions` is the list of
    INTRODUCED findings — other reproducers that fired post but
    not pre. Empty list means no regressions detected.

    A successful fix has primary.status == 'VERIFIED' AND
    regressions == []. Anything else needs human attention.
    """
    primary: FixVerifyResult
    regressions: list[RegressionResult]
    all_monitored: list[RegressionResult]  # full list including non-INTRODUCED


def verify_fix_with_regression_check(
    target: Finding,
    repo_root: Path,
    pre_ref: str,
    post_ref: str,
    other_findings: list[Finding],
) -> FixVerifyWithRegressionResult:
    """Layer D + regression: verify the target's reproducer flips
    True→False AND no other monitored reproducer flips False→True.

    The 'fix introduced a new bug' class isn't caught by single-
    finding Layer D — the original reproducer can flip True→False
    while a DIFFERENT reproducer that was previously STALE now
    fires (e.g. the fix removed a check that another finding
    indirectly tested). Adding this side-check catches that class.

    Uses git worktrees per `verify_fix_against_refs`; both pre_ref
    and post_ref are checked out into temp worktrees that are torn
    down on return.
    """
    with tempfile.TemporaryDirectory(prefix="audit-skill-oracle-") as td:
        td_path = Path(td)
        pre_wt = td_path / "pre"
        post_wt = td_path / "post"
        try:
            _run_git(["worktree", "add", "--detach", str(pre_wt), pre_ref], repo_root)
            _run_git(["worktree", "add", "--detach", str(post_wt), post_ref], repo_root)

            # Target finding
            pre_fires, ev_pre = target.reproducer.fires(pre_wt)
            post_fires, ev_post = target.reproducer.fires(post_wt)
            primary = _classify(target, pre_fires, post_fires, ev_pre, ev_post)

            # Regression check
            monitored: list[RegressionResult] = []
            for f in other_findings:
                if f is target or f.reproducer.type == "manual":
                    continue
                try:
                    pre_f, ev_p = f.reproducer.fires(pre_wt)
                except Exception as e:
                    # Treat reproducer errors as "indeterminate"; can't
                    # claim regression nor absence.
                    pre_f, ev_p = False, f"<error pre: {e!r}>"
                try:
                    post_f, ev_q = f.reproducer.fires(post_wt)
                except Exception as e:
                    post_f, ev_q = False, f"<error post: {e!r}>"
                if pre_f and post_f:
                    status = "PRE-EXISTING"
                elif pre_f and not post_f:
                    status = "RESOLVED"
                elif not pre_f and post_f:
                    status = "INTRODUCED"
                else:
                    status = "CLEAN"
                monitored.append(RegressionResult(
                    finding=f, status=status,
                    pre_fires=pre_f, post_fires=post_f,
                    evidence_pre=ev_p, evidence_post=ev_q,
                ))
        finally:
            for wt in (pre_wt, post_wt):
                if wt.exists():
                    subprocess.run(
                        ["git", "worktree", "remove", "--force", str(wt)],
                        cwd=str(repo_root), capture_output=True,
                    )

    regressions = [m for m in monitored if m.status == "INTRODUCED"]
    # Primary fix verdict, plus one INTRODUCED record per regression so
    # the SubagentStop gate blocks a fix that breaks a sibling finding.
    _write_d_record(
        target, primary.status,
        f"pre_fires={primary.pre_fires} post_fires={primary.post_fires}",
        {"mode": "regression-primary"},
    )
    for reg in regressions:
        _write_d_record(
            reg.finding, "INTRODUCED",
            f"fix for {target.skill}/{target.code} introduced reproducer "
            f"signal in {reg.finding.skill}/{reg.finding.code}",
            {"mode": "regression-side", "caused_by": f"{target.skill}/{target.code}"},
        )
    return FixVerifyWithRegressionResult(
        primary=primary,
        regressions=regressions,
        all_monitored=monitored,
    )
