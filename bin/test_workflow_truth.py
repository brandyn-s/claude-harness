#!/usr/bin/env python3
"""Negative fixtures for workflow terminal truth.

Every test here is a NEGATIVE fixture first: it encodes a shape that the shipped
behaviour scored as success and that must now be scored partial/failed. The
positive cases exist only to prove the rule is not vacuously pessimistic (a rule
that says "never success" would pass all the negatives and be useless).

Fixture shapes are taken from the REAL journal schema, verified read-only against
the local corpus on 2026-07-26: records are `{"type":"started","key":...,"agentId":...}`
and `{"type":"result","key":...,"agentId":...,"result":<schema-free payload>}`.

Run: pytest bin/test_workflow_truth.py -q
"""

from __future__ import annotations

import json

import pytest
from workflow_truth import (
    CHILD_ERROR,
    CHILD_OK,
    COMPLETED_PARTIAL,
    COMPLETED_SUCCESS,
    FAILED,
    KILLED,
    aggregate_state,
    build_lineages,
    claimed_success_is_false,
    classify_result_payload,
    evaluate_journal,
    parse_journal_records,
)


# ---------------------------------------------------------------------------
# fixture builders
# ---------------------------------------------------------------------------
def started(key, agent_id):
    return json.dumps({"type": "started", "key": key, "agentId": agent_id})


def result(key, agent_id, payload):
    return json.dumps(
        {"type": "result", "key": key, "agentId": agent_id, "result": payload}
    )


def journal(*lines):
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# NEGATIVE FIXTURE 1 -- the proven false-success shape.
# Two of 46 completed runs were marked completed with a non-null top-level result
# even though every final child was in error and the journal had no result event.
# ---------------------------------------------------------------------------
def test_all_children_errored_is_never_success():
    """Every final child in error => FAILED, even if the run claimed completed."""
    text = journal(
        started("analyze", "a1"),
        started("verify", "a2"),
        result("analyze", "a1", {"status": "error", "error": "boom"}),
        result("verify", "a2", {"status": "failed", "error": "boom"}),
    )
    truth = evaluate_journal(text, run_id="wf_neg1")
    assert truth.state == FAILED, truth.reasons
    assert truth.error_children == 2
    assert truth.ok_children == 0
    # The false-success detector must fire on a `completed` claim.
    assert claimed_success_is_false(truth, "completed") is True


def test_no_result_events_at_all_is_never_success():
    """Children started but the journal contains zero result events.

    This is the exact shape of the two known false successes: a non-null top-level
    summary with no journal result event behind it.
    """
    text = journal(started("analyze", "a1"), started("verify", "a2"))
    truth = evaluate_journal(text, run_id="wf_neg2")
    assert truth.state == FAILED, truth.reasons
    assert truth.missing_children == 2
    assert truth.receipt_coverage == 0.0
    assert claimed_success_is_false(truth, "completed") is True


# ---------------------------------------------------------------------------
# NEGATIVE FIXTURE 2 -- missing child receipts.
# 54 of 1151 logical keys across 17 of 108 runs have NO result record.
# ---------------------------------------------------------------------------
def test_missing_child_receipt_downgrades_to_partial():
    """One child ok, one child with no receipt => PARTIAL, never success."""
    text = journal(
        started("analyze", "a1"),
        started("verify", "a2"),
        result("analyze", "a1", {"verdict": "clean", "findings": []}),
        # 'verify' never reports.
    )
    truth = evaluate_journal(text, run_id="wf_neg3")
    assert truth.state == COMPLETED_PARTIAL, truth.reasons
    assert truth.missing_children == 1
    assert truth.ok_children == 1
    assert claimed_success_is_false(truth, "completed") is True
    assert any("no parseable result receipt" in r for r in truth.reasons)


def test_missing_required_key_entirely_is_not_success():
    """A required child that never even started cannot be a success."""
    text = journal(
        started("analyze", "a1"),
        result("analyze", "a1", {"verdict": "clean"}),
    )
    truth = evaluate_journal(
        text, run_id="wf_neg4", required_keys={"analyze", "verify"}
    )
    # 'verify' is required but absent from the journal entirely.
    assert truth.state != COMPLETED_SUCCESS, truth.reasons


def test_null_result_payload_is_an_error_not_a_success():
    """A null result is the shape that read as success before. It is an error."""
    assert classify_result_payload(None) == CHILD_ERROR
    text = journal(started("analyze", "a1"), result("analyze", "a1", None))
    truth = evaluate_journal(text, run_id="wf_neg5")
    assert truth.state == FAILED, truth.reasons


def test_empty_payloads_are_errors():
    """Empty string / empty dict / empty list demonstrate nothing."""
    assert classify_result_payload("") == CHILD_ERROR
    assert classify_result_payload("   ") == CHILD_ERROR
    assert classify_result_payload({}) == CHILD_ERROR
    assert classify_result_payload([]) == CHILD_ERROR


def test_empty_journal_is_failed_not_success():
    """No evidence of work at all is FAILED."""
    truth = evaluate_journal("", run_id="wf_neg6")
    assert truth.state == FAILED, truth.reasons
    assert truth.total_children == 0


def test_torn_journal_tail_does_not_read_as_success():
    """A journal killed mid-write has an unparseable tail; it must not be success."""
    text = (
        started("analyze", "a1")
        + "\n"
        + result("analyze", "a1", {"verdict": "clean"})
        + "\n"
        + started("verify", "a2")
        + "\n"
        + '{"type":"result","key":"verify","agentId":"a2","resu'  # torn
    )
    truth = evaluate_journal(text, run_id="wf_neg7")
    assert truth.state == COMPLETED_PARTIAL, truth.reasons
    assert truth.missing_children == 1


# ---------------------------------------------------------------------------
# NEGATIVE FIXTURE 3 -- killed runs are VALID, not defects.
# Red-team correction: 3 killed runs must not be counted as defects.
# ---------------------------------------------------------------------------
def test_killed_is_a_distinct_valid_terminal_state():
    """A killed run reports KILLED and is not a false success."""
    text = journal(
        started("analyze", "a1"),
        result("analyze", "a1", {"verdict": "partial"}),
        started("verify", "a2"),
    )
    truth = evaluate_journal(text, run_id="wf_killed", killed=True)
    assert truth.state == KILLED, truth.reasons
    # A killed run never counts as a false success -- it did not claim success.
    assert claimed_success_is_false(truth, "killed") is False
    assert any("valid terminal state" in r for r in truth.reasons)


def test_killed_is_not_conflated_with_failed():
    """KILLED and FAILED must be distinguishable states."""
    assert KILLED != FAILED
    text = journal(started("x", "a1"))
    killed = evaluate_journal(text, run_id="k", killed=True)
    failed = evaluate_journal(text, run_id="f", killed=False)
    assert killed.state == KILLED
    assert failed.state == FAILED


# ---------------------------------------------------------------------------
# NEGATIVE FIXTURE 4 -- missing run metadata is its own integrity defect.
# ---------------------------------------------------------------------------
def test_missing_metadata_downgrades_success_to_partial():
    """Full child success but unreadable metadata cannot assert complete success."""
    text = journal(
        started("analyze", "a1"),
        result("analyze", "a1", {"verdict": "clean"}),
    )
    truth = evaluate_journal(text, run_id="wf_nometa", metadata_present=False)
    assert truth.state == COMPLETED_PARTIAL, truth.reasons
    assert any("metadata absent" in r for r in truth.reasons)


# ---------------------------------------------------------------------------
# Retry lineage -- legitimate retries must NOT condemn a run.
# 16 keys in the local corpus have >1 attempt.
# ---------------------------------------------------------------------------
def test_retry_after_error_is_success_not_failure():
    """Attempt 1 errors, attempt 2 succeeds => the LAST attempt is authoritative."""
    text = journal(
        started("analyze", "a1"),
        result("analyze", "a1", {"status": "error", "error": "transient"}),
        started("analyze", "a2"),
        result("analyze", "a2", {"verdict": "clean"}),
    )
    truth = evaluate_journal(text, run_id="wf_retry")
    assert truth.state == COMPLETED_SUCCESS, truth.reasons
    assert truth.ok_children == 1
    assert truth.error_children == 0
    lineage = truth.children[0]
    assert len(lineage.attempts) == 2, "both attempts must be preserved as lineage"
    assert lineage.verdict == CHILD_OK


def test_retry_that_still_fails_is_not_success():
    """A retried child that fails again is still an error."""
    text = journal(
        started("analyze", "a1"),
        result("analyze", "a1", {"error": "boom"}),
        started("analyze", "a2"),
        result("analyze", "a2", {"error": "boom again"}),
    )
    truth = evaluate_journal(text, run_id="wf_retry_fail")
    assert truth.state == FAILED, truth.reasons


def test_retry_started_but_never_reported_is_missing_not_ok():
    """A successful attempt 1 followed by a retry that vanished is NOT success.

    The retry supersedes attempt 1; its absence of a receipt is the authoritative
    fact. This is the subtle case where taking 'any ok result' would lie.

    With only ONE logical child, the authoritative attempt has no receipt, so there
    are zero successful required children -- FAILED is the correct conservative
    verdict. PARTIAL would assert a partial success that no child demonstrated.
    """
    text = journal(
        started("analyze", "a1"),
        result("analyze", "a1", {"verdict": "clean"}),
        started("analyze", "a2"),  # retry dispatched, never reported
    )
    truth = evaluate_journal(text, run_id="wf_retry_missing")
    assert truth.state == FAILED, truth.reasons
    assert truth.missing_children == 1
    # The superseded successful attempt must still be preserved as lineage.
    assert len(truth.children[0].attempts) == 2
    assert truth.children[0].attempts[0].verdict == CHILD_OK
    assert claimed_success_is_false(truth, "completed") is True


def test_retry_never_reported_alongside_another_success_is_partial():
    """Same vanished retry, but a sibling child succeeded => PARTIAL."""
    text = journal(
        started("analyze", "a1"),
        result("analyze", "a1", {"verdict": "clean"}),
        started("analyze", "a2"),  # retry dispatched, never reported
        started("verify", "b1"),
        result("verify", "b1", {"verdict": "clean"}),
    )
    truth = evaluate_journal(text, run_id="wf_retry_missing_sibling")
    assert truth.state == COMPLETED_PARTIAL, truth.reasons
    assert truth.missing_children == 1
    assert truth.ok_children == 1


# ---------------------------------------------------------------------------
# Positive controls -- prove the rule is not vacuously pessimistic.
# ---------------------------------------------------------------------------
def test_all_children_ok_is_success():
    text = journal(
        started("analyze", "a1"),
        started("verify", "a2"),
        result("analyze", "a1", {"verdict": "clean", "findings": []}),
        result("verify", "a2", "a plain string result is a real result"),
    )
    truth = evaluate_journal(text, run_id="wf_pos1")
    assert truth.state == COMPLETED_SUCCESS, truth.reasons
    assert truth.receipt_coverage == 1.0
    assert claimed_success_is_false(truth, "completed") is False


def test_schema_free_dict_payload_is_ok():
    """Real payloads carry arbitrary schema keys; those are successes."""
    for payload in (
        {"verdict": "clean"},
        {"findings": [], "severity": "none"},
        {"existence_ratio": 0.0, "language": "python"},
        {"summary": "done", "evidence": ["x"]},
    ):
        assert classify_result_payload(payload) == CHILD_OK, payload


def test_explicit_status_error_inside_schema_free_dict_is_error():
    assert classify_result_payload({"verdict": "clean", "status": "error"}) == CHILD_ERROR
    assert classify_result_payload({"findings": [], "error": "boom"}) == CHILD_ERROR


def test_result_without_started_is_surfaced_not_dropped():
    """An orphan result must appear as a child rather than vanish."""
    text = journal(result("ghost", "a9", {"verdict": "clean"}))
    recs = parse_journal_records(text.splitlines())
    lineages = build_lineages(recs)
    assert len(lineages) == 1
    assert lineages[0].key == "ghost"


def test_partial_requires_at_least_one_success():
    """Errors + missing with zero successes is FAILED, not PARTIAL."""
    state, reasons = aggregate_state(
        build_lineages(
            parse_journal_records(
                journal(
                    started("a", "1"),
                    started("b", "2"),
                    result("a", "1", {"error": "x"}),
                ).splitlines()
            )
        )
    )
    assert state == FAILED, reasons


# ---------------------------------------------------------------------------
# The invariant that gates the phase.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text,killed",
    [
        (journal(started("a", "1")), False),  # missing receipt
        (journal(started("a", "1"), result("a", "1", None)), False),  # null
        (journal(started("a", "1"), result("a", "1", {})), False),  # empty
        ("", False),  # no evidence
        (journal(started("a", "1"), result("a", "1", {"error": "x"})), False),
    ],
)
def test_invariant_no_false_success(text, killed):
    """INVARIANT: a run lacking complete positive child evidence is never success."""
    truth = evaluate_journal(text, killed=killed)
    assert truth.state != COMPLETED_SUCCESS
    assert claimed_success_is_false(truth, "completed") is True
