"""``act_on`` — the pre-action gate that turns a Phase 2 findings tracker
into an oracle-verified worklist.

Purpose: in the May 2026 fix campaign, 38% of attempted fixes turned
out to be against findings that had already been resolved by parallel
work. That's the "stale finding" problem the oracle exists to prevent.
But the oracle was only being invoked AFTER findings were dispatched
to fix-agents — too late. ``act_on`` closes that gap: it is the
mandatory pre-action gate that every fix-orchestrator workflow must
call before dispatching any fix work.

The function takes a findings source (YAML, JSON, or — via the
tracker-to-yaml conversion in ``oracle.tracker``) a markdown
tracker file. It runs Layer A reverify against each finding, then
returns ONLY the STILL-FIRES + MANUAL + ERROR ones. STALE findings
are dropped (with their evidence logged to the trace).

The CLI exposes this as:

  bin/audit-skill-oracle.py act-on FINDINGS.yaml --out WORKLIST.yaml

After running, the orchestrator dispatches fix-agents only against
WORKLIST.yaml. The 38% stale rate observed in this session would
drop close to zero with this gate in place.
"""
from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from pathlib import Path

from .finding import Finding, dump_findings, load_findings
from .reverify import ReverifyResult, reverify

# Worklist staleness budget. After act_on emits a worklist, any
# fix-orchestrator consuming it must verify the worklist's
# `verified_at` is no older than this many seconds — otherwise the
# orchestrator should re-run act_on. Default 30 minutes; override
# via env var. Without this, a worklist computed at T=0 and acted
# on at T=6h races parallel work the orchestrator didn't know
# about — the exact 38%-stale-rate failure act_on was built to
# prevent, just shifted from "no gate" to "gate but stale cache."
WORKLIST_TTL_SECONDS = 30 * 60


@dataclasses.dataclass
class ActOnReport:
    """What act_on produces — both the worklist and the diagnostic
    summary so the orchestrator can report 'X stale, Y still-fires,
    Z manual, W error' to the user.

    ``triage_filtered`` carries findings whose ``triage_status`` was
    one of STALE / FIXED / FALSE_POSITIVE / DEFER — these are dropped
    from the worklist BEFORE reverify even runs (the operator has
    explicitly closed them; re-running the reproducer would be wasted
    work). Added 2026-05-25 alongside the triage_status schema."""
    worklist: list[Finding]            # STILL-FIRES + MANUAL + ERROR
    stale: list[ReverifyResult]         # dropped from worklist
    still_fires: list[ReverifyResult]
    manual: list[ReverifyResult]
    error: list[ReverifyResult]
    triage_filtered: list[Finding] = dataclasses.field(default_factory=list)
    # ISO-8601 UTC timestamp of the reverify pass that produced this
    # report. Consumers (fix-orchestrators) should refuse to act on
    # a worklist whose verified_at is older than WORKLIST_TTL_SECONDS
    # — the worklist may have raced parallel work in between.
    verified_at: str = ""

    @property
    def stale_rate(self) -> float:
        total = len(self.stale) + len(self.still_fires) + len(self.manual) + len(self.error)
        return len(self.stale) / total if total else 0.0


def act_on(findings: list[Finding], repo_root: Path) -> ActOnReport:
    """Run reverify against ``findings`` and partition the results.

    Returns an ActOnReport whose ``worklist`` field is the subset
    callers should act on (STILL-FIRES + MANUAL + ERROR). STALE
    findings are dropped from the worklist but kept in the report
    so the orchestrator can summarize them.

    Two-stage filter:
      1. Triage filter: drop findings whose triage_status is closed
         (STALE/FIXED/FALSE_POSITIVE/DEFER). Operator has explicitly
         marked them not-actionable; do not waste reverify cycles.
      2. Reverify filter (Layer A): for the remaining findings, run
         the reproducer and partition by status."""
    actionable = [f for f in findings if f.is_actionable()]
    triage_filtered = [f for f in findings if not f.is_actionable()]

    results = reverify(actionable, repo_root)
    still_fires = [r for r in results if r.status == "STILL-FIRES"]
    stale = [r for r in results if r.status == "STALE"]
    manual = [r for r in results if r.status == "MANUAL"]
    error = [r for r in results if r.status == "ERROR"]
    # Persist the verdict on each surviving finding so the worklist YAML
    # (and the Phase 4 report built from it) carries the oracle's actual
    # classification. Without this, downstream consumers re-inferred the
    # verdict from reproducer type alone — and an ERROR (broken
    # instrument) finding rendered as "STILL-FIRES / needs-fix"
    # (2026-06-12 finding audit-skill/D2).
    for r in still_fires + manual + error:
        r.finding.extra["oracle_verdict"] = r.status
    worklist = [r.finding for r in still_fires + manual + error]
    return ActOnReport(
        worklist=worklist,
        stale=stale,
        still_fires=still_fires,
        manual=manual,
        error=error,
        triage_filtered=triage_filtered,
        verified_at=datetime.now(timezone.utc).isoformat(),
    )


def dispatchable_only(report: ActOnReport) -> list[Finding]:
    """The auto-checkable dispatch subset: STILL-FIRES findings only.

    MANUAL findings can't be auto-verified (validate_worklist.py Gate 1
    rejects them) and ERROR findings have a broken instrument (Gate 4
    rejects them) — emitting either into a fix-batch worklist just moves
    the rejection downstream. The 2026-08-22 campaign-11 close-out hit
    exactly this: a bare `act-on --out` worklist (1 STILL-FIRES + 33
    MANUAL) failed the skill's own Step-0 validation and needed an
    ad-hoc filter. `--auto-only` on the CLI routes through this helper
    so the emitted worklist is dispatchable as-written.
    """
    return [r.finding for r in report.still_fires]


def worklist_is_fresh(verified_at: str, ttl_seconds: int = WORKLIST_TTL_SECONDS) -> tuple[bool, str]:
    """Check whether a worklist's verified_at is within the TTL.

    Returns (is_fresh, reason). Consumers should refuse to act when
    is_fresh is False and re-invoke act_on instead. Without this
    check, a fix-orchestrator could act on a 6-hour-old worklist
    while parallel work has resolved findings — exact 38%-stale
    failure mode shifted from "no gate" to "stale-cache gate."
    """
    if not verified_at:
        return False, "worklist has no verified_at stamp; cannot validate freshness"
    try:
        ts = datetime.fromisoformat(verified_at)
    except ValueError as e:
        return False, f"verified_at {verified_at!r} is not a valid ISO-8601 timestamp: {e}"
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    if age > ttl_seconds:
        return False, (
            f"worklist verified_at {verified_at} is {age:.0f}s old "
            f"(TTL: {ttl_seconds}s) — re-run act_on before dispatching"
        )
    return True, f"verified_at {verified_at} (age {age:.0f}s)"


def format_act_on_summary(report: ActOnReport) -> str:
    """Human-readable summary string."""
    import re
    from collections import Counter

    total = (len(report.stale) + len(report.still_fires)
             + len(report.manual) + len(report.error)
             + len(report.triage_filtered))
    lines = [
        f"act_on summary: {total} findings reviewed",
        f"  STILL-FIRES: {len(report.still_fires)} (will dispatch)",
        f"  MANUAL:      {len(report.manual)} (human review)",
        f"  ERROR:       {len(report.error)} (reproducer broken)",
        f"  STALE:       {len(report.stale)} (DROPPED — already resolved)",
        f"  TRIAGE-CLOSED: {len(report.triage_filtered)} (operator-closed: STALE/FIXED/FALSE_POSITIVE/DEFER)",
        f"  stale rate:  {report.stale_rate:.1%}",
        f"  verified_at: {report.verified_at or '(unstamped)'}",
    ]
    if report.stale:
        # Evidence buckets make instrument failure visible at-a-glance:
        # in the 2026-06-12 campaign, 68 STALE verdicts with `bash rc=2`
        # were actually truncated commands erroring (bash parse errors),
        # not resolved bugs — invisible until bucketed by hand. rc=2 on
        # a bash-wrapped grep usually means the INNER command errored.
        buckets = Counter()
        for r in report.stale:
            m = re.search(r"\brc=(-?\d+)", r.evidence or "")
            rc = m.group(1) if m else "?"
            buckets[f"{r.finding.reproducer.type} rc={rc}"] += 1
        pretty = ", ".join(f"{k}: {n}" for k, n in buckets.most_common())
        lines.append(f"  stale evidence: {pretty}")
        bash_rc2 = buckets.get("bash rc=2", 0)
        if bash_rc2 >= 3:
            lines.append(
                f"  WARNING: {bash_rc2} STALE verdicts are `bash rc=2` — for "
                f"bash-wrapped greps that exit code usually means the command "
                f"ERRORED (bad pattern/path/truncation), not that the bug is "
                f"fixed. Inspect before trusting the drop."
            )
    return "\n".join(lines)
