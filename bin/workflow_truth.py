#!/usr/bin/env python3
"""Derive TRUTHFUL workflow terminal state from journal evidence + durable child receipts.

WHY THIS EXISTS
---------------
Finding (red-team-corrected): of 46 *completed* workflow runs in the 14-day window,
2 were marked completed with a non-null top-level result even though every final
child was in error and the journal contained no result event -- a 2/46 = 4.3%
FALSE-SUCCESS rate. Three additional runs were `killed`, which is a VALID terminal
state and is NOT a defect. One run had missing metadata (a separate
metadata-integrity defect).

Empirically verified against the local corpus on 2026-07-26 (108 journals,
read-only probe):

  * journal.jsonl carries exactly TWO record types: `started` and `result`.
      started: keys = [agentId, key, type]
      result:  keys = [agentId, key, result, type]
  * There is NO terminal workflow record type, and NO run-level metadata file on
    disk. So "did this run succeed?" is not answerable from the journal alone.
  * The `result` payload is SCHEMA-FREE: 990 dicts (whose keys are whatever the
    agent's StructuredOutput schema happened to be -- verdict/findings/...) and
    107 bare strings. There is no status field, no error field, no receipt.
  * 54 of 1151 logical keys have NO result record at all, spread across 17 of 108
    runs. Those are precisely the children that today read as success.

CONSEQUENCE FOR THE DESIGN
--------------------------
Because the result payload is schema-free, truth CANNOT come from parsing it more
cleverly. It must come from a separate, explicit receipt layer plus a conservative
aggregation rule. This module therefore:

  1. reconstructs attempt lineage per logical `key` from the append-only journal;
  2. designates ONE authoritative final attempt per key (last started attempt);
  3. treats a missing/unknown required result as PARTIAL or FAILED -- NEVER success;
  4. keeps `completed_success`, `completed_partial`, `failed`, and `killed` as
     four DISTINCT terminal states, so a deliberate kill is never scored a defect.

It is deliberately CONSERVATIVE: absence of evidence is never scored as success.
That is the whole point -- the shipped defect was optimism about missing evidence.

This module is pure and read-only. It does not mutate journals or emit receipts;
`workflow_receipt.py` owns receipt emission.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Terminal states. These are DISTINCT on purpose.
# ---------------------------------------------------------------------------
RUNNING = "running"
COMPLETED_SUCCESS = "completed_success"
COMPLETED_PARTIAL = "completed_partial"
FAILED = "failed"
KILLED = "killed"

#: `killed` is a valid terminal outcome, not a defect. Kept separate so defect
#: rates are computed over an eligible denominator (completed runs only).
TERMINAL_STATES = (COMPLETED_SUCCESS, COMPLETED_PARTIAL, FAILED, KILLED)

#: Result verdicts for a single child attempt.
CHILD_OK = "ok"
CHILD_ERROR = "error"
CHILD_MISSING = "missing"  # started, never produced a result record


class JournalIntegrityError(Exception):
    """Raised when a journal cannot be interpreted at all (not merely incomplete)."""


# ---------------------------------------------------------------------------
# Child result classification
# ---------------------------------------------------------------------------
def classify_result_payload(payload: Any) -> str:
    """Classify a single journal `result` payload as CHILD_OK or CHILD_ERROR.

    The payload is schema-free (verified: 990 dicts / 107 strings across the local
    corpus), so this uses an EXPLICIT, documented set of error signals and treats
    everything else as ok. Two deliberate choices:

    * ``None`` is an ERROR, not a success. A null result is exactly the shape the
      two known false-success runs presented.
    * An empty string / empty dict is an ERROR. An agent that returned nothing
      did not demonstrate success.

    A dict carrying an explicit status/error field is honoured when present; we do
    NOT invent meaning for the arbitrary schema keys around it.
    """
    if payload is None:
        return CHILD_ERROR

    if isinstance(payload, str):
        return CHILD_ERROR if not payload.strip() else CHILD_OK

    if isinstance(payload, dict):
        if not payload:
            return CHILD_ERROR
        # Honour an explicit self-reported status if the agent supplied one.
        for key in ("status", "state", "outcome"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip().lower() in {
                "error",
                "failed",
                "failure",
                "fatal",
            }:
                return CHILD_ERROR
        # An explicit error field with content is an error.
        for key in ("error", "exception", "traceback"):
            val = payload.get(key)
            if val not in (None, "", [], {}, False):
                return CHILD_ERROR
        return CHILD_OK

    if isinstance(payload, (list, tuple)):
        return CHILD_ERROR if len(payload) == 0 else CHILD_OK

    # Numbers, bools, and anything else: presence is the only signal available.
    return CHILD_OK


@dataclass
class Attempt:
    """One dispatch attempt of a logical child."""

    agent_id: str | None
    order: int
    result_present: bool = False
    verdict: str = CHILD_MISSING
    payload_kind: str | None = None


@dataclass
class ChildLineage:
    """All attempts for one logical child `key`, plus its authoritative verdict."""

    key: str | None
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def authoritative(self) -> Attempt:
        """The attempt whose outcome counts.

        Retries are legitimate (16 keys in the local corpus have >1 attempt), so a
        superseded failed attempt must not condemn the run. The LAST started
        attempt is authoritative; earlier attempts are lineage/context only.
        """
        if not self.attempts:
            raise JournalIntegrityError(f"child {self.key!r} has no attempts")
        return self.attempts[-1]

    @property
    def verdict(self) -> str:
        return self.authoritative.verdict

    @property
    def has_receipt(self) -> bool:
        """True only if the authoritative attempt produced a parseable result record."""
        return self.authoritative.result_present


@dataclass
class WorkflowTruth:
    """Computed terminal truth for one workflow run."""

    run_id: str
    state: str
    children: list[ChildLineage] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    metadata_present: bool = True

    # ---- derived counts (published separately; never collapsed to one boolean)
    @property
    def total_children(self) -> int:
        return len(self.children)

    @property
    def ok_children(self) -> int:
        return sum(1 for c in self.children if c.verdict == CHILD_OK)

    @property
    def error_children(self) -> int:
        return sum(1 for c in self.children if c.verdict == CHILD_ERROR)

    @property
    def missing_children(self) -> int:
        return sum(1 for c in self.children if c.verdict == CHILD_MISSING)

    @property
    def receipt_coverage(self) -> float:
        """Fraction of children whose authoritative attempt has a parseable receipt."""
        if not self.children:
            return 0.0
        return sum(1 for c in self.children if c.has_receipt) / len(self.children)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "state": self.state,
            "metadata_present": self.metadata_present,
            "total_children": self.total_children,
            "ok_children": self.ok_children,
            "error_children": self.error_children,
            "missing_children": self.missing_children,
            "receipt_coverage": round(self.receipt_coverage, 4),
            "reasons": list(self.reasons),
            "children": [
                {
                    "key": c.key,
                    "verdict": c.verdict,
                    "attempts": len(c.attempts),
                    "has_receipt": c.has_receipt,
                }
                for c in self.children
            ],
        }


# ---------------------------------------------------------------------------
# Journal parsing
# ---------------------------------------------------------------------------
def parse_journal_records(lines: Iterable[str]) -> list[dict]:
    """Parse journal lines into records, skipping blank/unparseable lines.

    Unparseable lines are skipped rather than fatal: a journal is append-only and
    may be torn at the tail if the process was killed mid-write. A torn tail must
    NOT make the whole run unreadable -- but it also must not read as success,
    which the aggregation rule below guarantees.
    """
    out: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def build_lineages(records: Iterable[dict]) -> list[ChildLineage]:
    """Reconstruct per-key attempt lineage from `started`/`result` records."""
    lineages: dict[Any, ChildLineage] = {}
    order = 0

    # First pass: started records establish attempts in journal order.
    for rec in records:
        if rec.get("type") != "started":
            continue
        key = rec.get("key")
        lin = lineages.setdefault(key, ChildLineage(key=key))
        lin.attempts.append(Attempt(agent_id=rec.get("agentId"), order=order))
        order += 1

    # Second pass: attach results to the matching attempt by agentId when possible.
    for rec in records:
        if rec.get("type") != "result":
            continue
        key = rec.get("key")
        lin = lineages.get(key)
        if lin is None:
            # A result with no started record: surface it as its own child so it
            # cannot be silently dropped.
            lin = lineages.setdefault(key, ChildLineage(key=key))
            lin.attempts.append(Attempt(agent_id=rec.get("agentId"), order=order))
            order += 1
        agent_id = rec.get("agentId")
        target = None
        for att in lin.attempts:
            if att.agent_id is not None and att.agent_id == agent_id:
                target = att
                break
        if target is None:
            # Fall back to the last attempt lacking a result.
            for att in lin.attempts:
                if not att.result_present:
                    target = att
                    break
        if target is None:
            target = lin.attempts[-1]
        payload = rec.get("result")
        target.result_present = True
        target.verdict = classify_result_payload(payload)
        target.payload_kind = type(payload).__name__

    return list(lineages.values())


# ---------------------------------------------------------------------------
# Aggregation -- the conservative rule
# ---------------------------------------------------------------------------
def aggregate_state(
    children: list[ChildLineage],
    *,
    killed: bool = False,
    metadata_present: bool = True,
    required_keys: set | None = None,
) -> tuple[str, list[str]]:
    """Compute the aggregate terminal state from child evidence.

    Rules, in order of precedence:

    1. ``killed`` is reported as-is. A deliberate kill is a VALID terminal state
       and is never reclassified as a defect.
    2. A run with NO children at all is FAILED, not success -- there is no
       evidence of work.
    3. Any required child MISSING a receipt  -> at best COMPLETED_PARTIAL.
       Missing/unknown is NEVER success. This is the rule that catches the two
       known false-success runs.
    4. Every required child in error         -> FAILED.
    5. Some errors / some ok                 -> COMPLETED_PARTIAL.
    6. All required children ok, all with receipts -> COMPLETED_SUCCESS.

    ``metadata_present=False`` is recorded as a separate integrity reason and
    downgrades success to partial: we cannot assert full success over an
    inventory we could not read.
    """
    reasons: list[str] = []

    if killed:
        reasons.append("run was killed; killed is a valid terminal state, not a defect")
        return KILLED, reasons

    if not children:
        reasons.append("no child records in journal; no evidence of work")
        return FAILED, reasons

    absent_required: list = []
    if required_keys is None:
        required = children
    else:
        required = [c for c in children if c.key in required_keys]
        # A required key that never appears in the journal MUST stay in the
        # denominator. Filtering the requirement set down to "keys we happened to
        # observe" is the same absent-evidence optimism that produced the shipped
        # false-success defect: the unaccounted-for child simply vanishes and the
        # run reports success. Caught by
        # test_missing_required_key_entirely_is_not_success.
        observed = {c.key for c in children}
        absent_required = sorted(
            str(k) for k in required_keys if k not in observed
        )
        if not required:
            reasons.append("none of the required keys appear in the journal")
            return FAILED, reasons

    missing = [c for c in required if not c.has_receipt]
    errored = [c for c in required if c.has_receipt and c.verdict == CHILD_ERROR]
    ok = [c for c in required if c.has_receipt and c.verdict == CHILD_OK]

    if absent_required:
        reasons.append(
            f"{len(absent_required)} required child(ren) never appear in the journal "
            f"({', '.join(absent_required)}); an unaccounted-for child is never success"
        )

    if missing:
        reasons.append(
            f"{len(missing)} required child(ren) have no parseable result receipt; "
            "missing evidence is never scored as success"
        )

    if errored:
        reasons.append(f"{len(errored)} required child(ren) reported an error verdict")

    if not metadata_present:
        reasons.append("run metadata absent; cannot assert complete success")

    # Every required child failed or is unaccounted for, and none succeeded.
    if not ok:
        reasons.append("no required child demonstrated success")
        return FAILED, reasons

    if missing or errored or absent_required or not metadata_present:
        return COMPLETED_PARTIAL, reasons

    reasons.append("all required children produced ok receipts")
    return COMPLETED_SUCCESS, reasons


def evaluate_journal(
    journal_text: str,
    *,
    run_id: str = "unknown",
    killed: bool = False,
    metadata_present: bool = True,
    required_keys: set | None = None,
) -> WorkflowTruth:
    """Evaluate a workflow run's terminal truth from its journal text."""
    records = parse_journal_records(journal_text.splitlines())
    children = build_lineages(records)
    state, reasons = aggregate_state(
        children,
        killed=killed,
        metadata_present=metadata_present,
        required_keys=required_keys,
    )
    return WorkflowTruth(
        run_id=run_id,
        state=state,
        children=children,
        reasons=reasons,
        metadata_present=metadata_present,
    )


def evaluate_journal_path(
    path: str,
    *,
    killed: bool = False,
    metadata_present: bool | None = None,
    required_keys: set | None = None,
) -> WorkflowTruth:
    """Evaluate a run directory's journal.jsonl on disk. Read-only."""
    run_id = os.path.basename(os.path.dirname(path)) or "unknown"
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    if metadata_present is None:
        # No run-level metadata file exists in the current layout (verified
        # 2026-07-26); treat presence as unknown-but-true so this flag stays a
        # caller-supplied signal rather than a fabricated one.
        metadata_present = True
    return evaluate_journal(
        text,
        run_id=run_id,
        killed=killed,
        metadata_present=metadata_present,
        required_keys=required_keys,
    )


def claimed_success_is_false(truth: WorkflowTruth, claimed_state: str) -> bool:
    """True when a run CLAIMS success but the evidence does not support it.

    This is the false-success detector. It is the metric with target 0.
    """
    if claimed_state not in ("completed", COMPLETED_SUCCESS, "success", "done"):
        return False
    return truth.state != COMPLETED_SUCCESS
