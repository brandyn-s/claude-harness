"""Prevent transient pull-request merge identity from breaking the trusted lane."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "provider-monitor-catalog-trusted.yml"


def test_trusted_provider_workflow_resolves_and_propagates_exact_candidate_sha() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "permissions:\n  contents: read\n  pull-requests: read" in source
    assert "github.event.pull_request.merge_commit_sha" not in source
    assert 'gh api "repos/$REPOSITORY/pulls/$PULL_NUMBER"' in source
    # REPLACED 2026-08-26. This used to assert the literal `for attempt in {1..10}`,
    # which pinned the retry CONSTRUCT and its 30-second budget rather than the
    # property. That budget was measured too short: on PR #2151 GitHub left
    # mergeable_state "unknown" for OVER TWO MINUTES with the platform fully
    # operational, so the step failed, provider-monitor-catalog-trusted cascaded off
    # it, and a plain re-run passed with no content change. The literal made the fix
    # look like a regression (feedback: tests can pin defects -- replace with the
    # inverse plus a documented reversal).
    #
    # What actually matters, asserted below: the poll is BOUNDED (no infinite loop in
    # a trust-lane job) and its failure message names the CAUSE, so an async-
    # mergeability timeout is not mistaken for a failed security check.
    # A bare `"budget_seconds=" in source` check was MISSED by a mutation that
    # restored the old construct and merely MENTIONED the token in a comment -- a
    # check matching prose about the code instead of the code (tdd-mutation-testing
    # item 32). Require a numeric assignment, and assert the retired construct is
    # ABSENT so the fix cannot be silently reverted.
    assert re.search(r"^\s*budget_seconds=\d+\s*$", source, re.MULTILINE), (
        "the poll must assign an explicit numeric time budget"
    )
    assert "for attempt in {1..10}" not in source, (
        "the retired 30-second retry construct must not come back; it produced a red "
        "PR on #2151 for a reason unrelated to the PR"
    )
    assert 'elapsed" -ge "$budget_seconds' in source, (
        "the loop must terminate on the budget -- an unbounded poll in a trust lane "
        "would hang the job rather than fail it"
    )
    assert "ASYNC mergeability computation" in source, (
        "the timeout message must name GitHub's async computation as the cause"
    )
    assert "NOT a defect in this pull request" in source, (
        "the timeout must not read as a content or security failure"
    )
    assert "API/permissions failure" in source, (
        "a failing pulls API call must be reported as such, not as an unresolved "
        "merge candidate -- the two causes send a reader to different places"
    )
    assert "candidate_sha=$candidate_sha" in source
    assert "candidate_revision: ${{ steps.candidate.outputs.candidate_sha }}" in source
    assert "candidate_revision: ${{ needs.inspect-candidate-trust.outputs.candidate_revision }}" in source
    assert "EXPECTED_CANDIDATE_SHA: ${{ needs.fetch-trusted-server-bundle.outputs.candidate_revision }}" in source
    assert "ref: ${{ steps.candidate.outputs.candidate_sha }}" in source
