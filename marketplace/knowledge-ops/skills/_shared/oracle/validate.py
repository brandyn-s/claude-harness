"""Schema enforcement at the fix-orchestrator boundary.

Root-cause fix for cause 6 (prose findings) and cause 3 (skippable
gate). The fix-orchestrator MUST consume only validated worklists —
prose findings, raw markdown trackers, and findings without
deterministic Reproducers are REJECTED at this boundary.

The validator's job is to make the oracle's gate non-skippable. If
the orchestrator can call ``validate_for_dispatch(<input>)`` and get
a structured failure when the input is a raw tracker, then "I forgot
to run act_on" stops being possible — the API rejects unverified
input.

Three rejection classes:

  REJECT_NO_REPRODUCER — finding has ``reproducer.type == "manual"``
    (or missing entirely). The oracle has not made a verification
    claim; the caller must either provide a deterministic predicate
    or route the finding to human review, not to a fix-batch.

  REJECT_NOT_REVERIFIED — finding has a non-manual Reproducer but
    no trace record (i.e., ``oracle.act_on()`` was never run against
    this worklist). The dispatch path requires fresh verification.

  REJECT_STALE_RECORD — the most recent reverify in the trace is
    older than ``MAX_REVERIFY_AGE_SECONDS`` (cause-4 fix: worklist
    TTL). Stale worklists must be re-verified before dispatch.

Callers use ``validate_for_dispatch()`` as a precondition. If it
returns a non-empty list, the orchestrator MUST NOT dispatch — emit
the rejections to the operator and stop.
"""
from __future__ import annotations

import dataclasses
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .finding import Finding, load_findings
from .specificity import is_nonspecific, specificity_verdict
from .trace import finding_id, read_records, trace_path

# Worklist TTL — fix for cause 4 (long-session state churn).
# Worklists older than this MUST be re-verified before dispatch.
MAX_REVERIFY_AGE_SECONDS = 30 * 60  # 30 minutes


REJECTION_CODES = (
    "REJECT_NO_REPRODUCER",
    "REJECT_NOT_REVERIFIED",
    "REJECT_STALE_RECORD",
    "REJECT_PROSE_INPUT",
    "REJECT_MALFORMED",
    "REJECT_NONSPECIFIC_REPRODUCER",
    "REJECT_UNVERIFIED_VERDICT",
)


@dataclasses.dataclass
class Rejection:
    code: str
    finding_id: str
    skill: str
    reason: str

    def __str__(self) -> str:
        return f"{self.code}  {self.skill}/{self.finding_id[:8]}  {self.reason}"


def validate_for_dispatch(
    worklist_path: Path,
    trace_path_override: Path | None = None,
    max_reverify_age_seconds: int = MAX_REVERIFY_AGE_SECONDS,
    repo_root: Path | None = None,
    enable_specificity: bool = True,
) -> list[Rejection]:
    """Return a list of rejections for the worklist. Empty list = OK to
    dispatch. Non-empty list = orchestrator must NOT dispatch; surface
    the rejections to the operator.

    Validates:
      - Input is a structured YAML/JSON file (not a raw markdown
        tracker).
      - Every finding has a non-manual Reproducer.
      - Every finding's reproducer is SPECIFIC, not vacuous
        (REJECT_NONSPECIFIC_REPRODUCER) — closes the proposer-grades-its-
        own-homework hole. When ``enable_specificity`` is False the check
        is skipped; when ``repo_root`` is None only the static layer runs
        (still catches the literal ``grep -q .`` class).
      - Every finding has a recent trace record (within the TTL).
    """
    rejections: list[Rejection] = []

    # Cause 3 + 6: reject prose input (markdown trackers must go
    # through `convert-tracker` first, then through `act_on`).
    if worklist_path.suffix == ".md":
        rejections.append(Rejection(
            code="REJECT_PROSE_INPUT",
            finding_id="",
            skill=str(worklist_path),
            reason=(
                f"input is a markdown tracker ({worklist_path.name}); "
                f"the fix-orchestrator API only accepts validated YAML "
                f"worklists. Run `audit-skill-oracle.py act-on <tracker.md> "
                f"--out <worklist.yaml>` first."
            ),
        ))
        return rejections

    try:
        findings = load_findings(worklist_path)
    except Exception as e:
        rejections.append(Rejection(
            code="REJECT_MALFORMED",
            finding_id="",
            skill=str(worklist_path),
            reason=f"failed to parse: {e!r}",
        ))
        return rejections

    # Build the trace index keyed by finding_id → latest Layer-A (reverify)
    # (timestamp, verdict). Only Layer A gates dispatch: the question is "does
    # the freshest reverify say this finding STILL-FIRES?" Tracking the verdict
    # (not just the timestamp) closes the verdict-blind hole where an ERROR
    # verdict (broken instrument) or STALE verdict (already resolved) passed.
    trace_records = read_records(trace_path_override or trace_path())
    latest_by_id: dict[str, tuple[datetime, str]] = {}
    for rec in trace_records:
        if rec.layer != "A":
            continue
        try:
            ts = datetime.fromisoformat(rec.ts)
        except (ValueError, TypeError):
            continue
        existing = latest_by_id.get(rec.finding_id)
        if existing is None or ts > existing[0]:
            latest_by_id[rec.finding_id] = (ts, rec.verdict)

    now = datetime.now(timezone.utc)
    for f in findings:
        fid = finding_id(f.skill, f.code, f.description)

        # Cause 6: reject manual findings.
        if f.reproducer.type == "manual":
            rejections.append(Rejection(
                code="REJECT_NO_REPRODUCER",
                finding_id=fid,
                skill=f.skill,
                reason=(
                    "Reproducer is type=manual; the oracle has not made a "
                    "verification claim. Route to human review, not to a "
                    "fix-batch."
                ),
            ))
            continue

        # Specificity guard: a vacuous predicate (e.g. `grep -q .`) fires
        # regardless of content, so its STILL-FIRES verdict certifies
        # nothing — the proposer graded its own homework. Reject before
        # the trace checks; a non-specific reproducer is unfixable-as-is.
        if enable_specificity:
            verdict, ev = specificity_verdict(f.reproducer, repo_root)
            if is_nonspecific(verdict):
                rejections.append(Rejection(
                    code="REJECT_NONSPECIFIC_REPRODUCER",
                    finding_id=fid,
                    skill=f.skill,
                    reason=(
                        f"reproducer is non-specific ({verdict}): {ev}. The "
                        f"predicate fires regardless of content; rewrite it to "
                        f"test the actual bug, or route to human review."
                    ),
                ))
                continue

        # Cause 3: require a Layer-A trace record (proves act_on ran).
        latest = latest_by_id.get(fid)
        if latest is None:
            rejections.append(Rejection(
                code="REJECT_NOT_REVERIFIED",
                finding_id=fid,
                skill=f.skill,
                reason=(
                    "no Layer-A trace record for this finding; run "
                    "`audit-skill-oracle.py act-on <findings> --out <worklist>` "
                    "to produce a verified worklist before dispatch."
                ),
            ))
            continue
        latest_ts, latest_verdict = latest

        # Cause 4: reject stale records (worklist TTL).
        age_seconds = (now - latest_ts).total_seconds()
        if age_seconds > max_reverify_age_seconds:
            rejections.append(Rejection(
                code="REJECT_STALE_RECORD",
                finding_id=fid,
                skill=f.skill,
                reason=(
                    f"latest reverify was {int(age_seconds)}s ago "
                    f"(> {max_reverify_age_seconds}s TTL); re-run "
                    f"`audit-skill-oracle.py act-on` before dispatch."
                ),
            ))
            continue

        # Verdict-blind-gate fix: the freshest reverify must say STILL-FIRES.
        # ERROR (the reproducer crashed — never demonstrated the bug) and STALE
        # (already resolved) are NOT dispatchable. Previously only freshness was
        # checked, so an ERROR-verdict finding sailed through the gate.
        if latest_verdict != "STILL-FIRES":
            rejections.append(Rejection(
                code="REJECT_UNVERIFIED_VERDICT",
                finding_id=fid,
                skill=f.skill,
                reason=(
                    f"latest Layer-A reverify verdict is {latest_verdict!r}, not "
                    f"STILL-FIRES; only a finding whose reproducer actually fired is "
                    f"dispatchable (ERROR=broken instrument, STALE=already resolved). "
                    f"Fix the reproducer or re-run act_on."
                ),
            ))

    return rejections


def format_rejections(rejections: list[Rejection]) -> str:
    """Human-readable rejection report for the operator."""
    if not rejections:
        return "validate_for_dispatch: OK (no rejections; worklist is dispatchable)"
    by_code: dict[str, list[Rejection]] = {}
    for r in rejections:
        by_code.setdefault(r.code, []).append(r)
    lines = [
        f"validate_for_dispatch: REJECTED ({len(rejections)} finding(s) blocked)",
    ]
    for code, rs in by_code.items():
        lines.append(f"\n  {code} ({len(rs)}):")
        for r in rs:
            lines.append(f"    {r.skill}: {r.reason}")
    return "\n".join(lines)


# ── Advisory reproducer-smell warnings (never gate dispatch) ──────────
#
# Three authoring failure classes recurred in the 2026-06-12 campaign:
#   1. Deployed-path probes (`~/.claude/...`) — adjudicate the DEPLOYED
#      tree instead of the tree under test, so a fix in a worktree can
#      never flip them pre-merge (3 instances, all false STILL-FIRES
#      until rewritten repo-relative).
#   2. Stateful appends (`>>` to a persistent path) — a stale line from
#      a prior run keeps the predicate firing after the fix lands
#      (variant-analysis caught its own instance).
# Both are legitimate in narrow cases (G1 deployment findings probe
# deployment state on purpose; appends inside fresh mktemp dirs are
# fine), so these are WARNINGS for the operator, not rejections — per
# the pattern-maturity lifecycle, observe before enforcing.

_DEPLOYED_PATH_RE = re.compile(r"(?:~|\$HOME)/\.claude/")
_STATEFUL_APPEND_RE = re.compile(r">>\s*(?P<target>\S+)")
_RUN_SCOPED_HINT_RE = re.compile(r"mktemp|\$T\b|\$\{?TMPDIR|tmp_path|\$d\b")


def advisory_warnings(findings: list[Finding]) -> list[str]:
    """Return advisory warning strings for reproducer-authoring smells.

    Never gates dispatch; surfaced by `validate` and `act-on` so the
    operator sees the smell BEFORE a verdict-forensics session instead
    of after.
    """
    warnings: list[str] = []
    for f in findings:
        cmd = f.reproducer.command or ""
        if not cmd:
            continue
        if _DEPLOYED_PATH_RE.search(cmd):
            warnings.append(
                f"DEPLOYED_PATH_PROBE {f.skill}/{f.code}: reproducer references "
                f"~/.claude — it adjudicates the deployed tree, not the tree "
                f"under test, and cannot flip pre-merge. Use repo-root-relative "
                f"paths unless this is deliberately a deployment-state probe."
            )
        m = _STATEFUL_APPEND_RE.search(cmd)
        if m and not _RUN_SCOPED_HINT_RE.search(cmd):
            warnings.append(
                f"STATEFUL_APPEND {f.skill}/{f.code}: reproducer appends to "
                f"{m.group('target')!r} without a run-scoped dir (mktemp/"
                f"TMPDIR) — stale lines from prior runs can keep the predicate "
                f"firing after the fix lands."
            )
        # 3. Doc-decoupled suspects — the predicate never references the
        #    finding's own skill directory, so it may be probing host
        #    state, a sibling repo, or an unrelated file and would fire
        #    (or stay quiet) regardless of whether the skill is fixed.
        #    Measured 2026-08-22 (campaign-11 close-out): 38 of 81
        #    dispatched findings were already fixed in-tree but kept
        #    adjudicating STILL-FIRES on exactly this predicate class.
        #    Legitimate cross-cutting predicates exist (repo-root
        #    ledgers, hooks/ consumers), so this stays advisory.
        if (f.skill and f"skills/{f.skill}/" not in cmd
                and f.reproducer.type != "transcript_pattern"):
            warnings.append(
                f"DOC_DECOUPLED_SUSPECT {f.skill}/{f.code}: reproducer never "
                f"references skills/{f.skill}/ — verify it probes the "
                f"artifact under test (a predicate that can't see the skill's "
                f"files fires the same whether or not the bug is fixed)."
            )
    return warnings
