"""Fail-closed tests for the gather report lifecycle gate."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "report_lifecycle.py")
spec = importlib.util.spec_from_file_location("rl", SCRIPT)
rl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rl)


VALID_REPORT = textwrap.dedent(
    """
    # Report

    ## Metadata

    ```
    Run date: 2026-08-12 | version v1
    ```

    ## Active Findings

    ### [2026-08-12] [HIGH] Qualified configuration change
    - **Category**: CONFIGURATION
    - **Source**: https://example.test/change
    - **Baseline ref**: settings.json model
    - **What changed**: The configured value changed.
    - **Recommended edit**: Update settings.json after qualification.
    - **Verdict**: ADOPT
    - **Qualification**: PASSED — `pytest -q` returned 0 with 12 passed
    - **Verified**: yes — target and result re-read

    ### [2026-08-12] [LOW] Deferred configuration change
    - **Category**: CONFIGURATION
    - **Source**: https://example.test/issue/123
    - **Baseline ref**: settings.json feature
    - **What changed**: The upstream feature remains unavailable.
    - **Recommended edit**: Re-evaluate settings.json when the issue closes.
    - **Verdict**: DEFER
    - **Trigger**: upstream issue #123 reaches CLOSED
    - **Qualification**: not-applicable — upstream capability is absent
    - **Verified**: yes — issue state read

    ### [2026-08-12] [LOW] Rejected documentation-only change
    - **Category**: TRAINING
    - **Source**: https://example.test/docs
    - **Baseline ref**: docs/notes.md section 2
    - **What changed**: The page added an irrelevant example.
    - **Recommended edit**: Make no local change.
    - **Verdict**: REJECT — no runtime use case
    - **Qualification**: not-applicable — no edit proposed
    - **Verified**: yes — source read

    ## Watching

    | Item | Type |
    |------|------|
    | #1 | Bug |
    | #2 | Bug |

    ### Watching (Dormant)

    | Item | Type |
    |------|------|
    | #3 | Bug |

    ## Archived

    ### [2026-07-01] [LOW] Historical staged record
    - **Category**: CONFIGURATION
    - **Verdict**: TRIAL
    - **try-by**: 2026-07-15
    - **Verified**: yes
    """
)

QUALIFY_REPORT = textwrap.dedent(
    """
    # Report
    ## Active Findings
    ### [2026-08-12] [HIGH] Candidate configuration change
    - **Category**: CONFIGURATION
    - **Source**: https://example.test/candidate
    - **Baseline ref**: settings.json candidate
    - **What changed**: A candidate setting became available.
    - **Recommended edit**: Qualify the candidate before applying it.
    - **Verdict**: QUALIFY
    - **Qualification**: pending — run the disposable candidate suite
    - **Verified**: yes — source read
    """
)


def _write(tmp: str, text: str) -> str:
    path = os.path.join(tmp, "report.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def _run(text: str, *, json_output: bool = False) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as tmp:
        command = [sys.executable, SCRIPT, _write(tmp, text), "--today", "2026-08-12"]
        if json_output:
            command.append("--json")
        return subprocess.run(command, capture_output=True, text=True, check=False)


def _finding(*fields: str) -> str:
    return textwrap.dedent(
        """
        # Report
        ## Active Findings
        ### [2026-08-12] [HIGH] Mutation fixture
        - **Category**: CONFIGURATION
        - **Source**: https://example.test/mutation
        - **Baseline ref**: config.json test key
        - **What changed**: The mutation changes the test key.
        - **Recommended edit**: Apply only after qualification.
        {fields}
        """
    ).format(fields="\n".join(fields))


def test_valid_final_report_passes_and_archived_history_is_ignored():
    result = _run(VALID_REPORT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REPORT VALID" in result.stdout
    assert "active rows: 2" in result.stdout
    assert "dormant appendix: 1" in result.stdout


def test_unresolved_qualification_fails_before_presentation():
    result = _run(QUALIFY_REPORT)
    assert result.returncode == 1
    assert "UNRESOLVED QUALIFICATION" in result.stdout


@pytest.mark.parametrize("verdict", ("DOCUMENT", "RECOMMEND", "UNKNOWN"))
def test_illegal_verdict_tokens_fail_closed(verdict: str):
    report = _finding(
        f"- **Verdict**: {verdict}",
        "- **Qualification**: not-applicable — no runtime change",
        "- **Verified**: yes — source read",
    )
    result = _run(report)
    assert result.returncode == 1
    assert "INVALID VERDICT" in result.stdout


def test_missing_verdict_is_distinct_from_invalid_verdict():
    report = _finding(
        "- **Qualification**: not-applicable — no runtime change",
        "- **Verified**: yes — source read",
    )
    result = _run(report)
    assert result.returncode == 1
    assert "MISSING VERDICT" in result.stdout
    assert re.search(r"INVALID VERDICT:\s+0", result.stdout)


@pytest.mark.parametrize(
    ("field", "expected"),
    (
        ("Category", "MISSING REQUIRED FIELD"),
        ("Source", "MISSING REQUIRED FIELD"),
        ("Baseline ref", "MISSING REQUIRED FIELD"),
        ("What changed", "MISSING REQUIRED FIELD"),
        ("Recommended edit", "MISSING REQUIRED FIELD"),
        ("Qualification", "MISSING QUALIFICATION"),
        ("Verified", "MISSING VERIFIED"),
    ),
)
def test_required_field_deletion_mutations_fail(field: str, expected: str):
    report = VALID_REPORT.replace(
        next(line for line in VALID_REPORT.splitlines() if f"**{field}**" in line),
        "",
        1,
    )
    result = _run(report)
    assert result.returncode == 1
    assert expected in result.stdout


@pytest.mark.parametrize("placeholder", ("TBD", "unknown", "pending", "N/A"))
def test_required_field_placeholders_fail_closed(placeholder: str):
    report = VALID_REPORT.replace(
        "- **Source**: https://example.test/change",
        f"- **Source**: {placeholder}",
        1,
    )
    result = _run(report)
    assert result.returncode == 1
    assert "MISSING REQUIRED FIELD" in result.stdout


@pytest.mark.parametrize(
    "legacy",
    (
        "- **Verdict**: TRIAL\n- **try-by**: 2026-09-12",
        "- **Verdict**: DEFER\n- **Trigger**: next release\n- **What changed**: keep the old TRIAL until then",
        "- **Verdict**: DEFER\n- **Trigger**: next release\n- **try-by**: 2026-09-12",
    ),
)
def test_active_legacy_staged_state_fails_even_when_future_or_prose_only(legacy: str):
    report = _finding(
        legacy,
        "- **Qualification**: not-applicable — waiting on upstream",
        "- **Verified**: yes — source read",
    )
    result = _run(report)
    assert result.returncode == 1
    assert "LEGACY STAGED STATE" in result.stdout


def test_undated_active_legacy_prose_fails_but_archived_prose_does_not():
    report = textwrap.dedent(
        """
        # Report
        ## Active Findings
        ### Carried platform note
        - Keep the old TRIAL until upstream changes.
        ## Archived
        - Historical TRIAL records may remain here.
        """
    )
    result = _run(report)
    assert result.returncode == 1
    assert "line 5" in result.stdout
    assert "Historical TRIAL" not in result.stdout


def test_defer_without_trigger_fails_closed():
    report = _finding(
        "- **Verdict**: DEFER — revisit eventually",
        "- **Qualification**: not-applicable — waiting",
        "- **Verified**: yes — source read",
    )
    result = _run(report)
    assert result.returncode == 1
    assert "DEFER WITHOUT TRIGGER" in result.stdout


def test_inline_defer_trigger_remains_backward_compatible():
    report = _finding(
        "- **Verdict**: DEFER — trigger: issue #123 reaches CLOSED",
        "- **Qualification**: not-applicable — waiting on upstream",
        "- **Verified**: yes — source read",
    )
    result = _run(report)
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    "qualification",
    ("pending", "not run", "FAILED — pytest exited 1", "PASSED"),
)
def test_adopt_rejects_non_evidentiary_qualification_mutations(qualification: str):
    report = _finding(
        "- **Verdict**: ADOPT",
        f"- **Qualification**: {qualification}",
        "- **Verified**: yes — source read",
    )
    result = _run(report)
    assert result.returncode == 1
    assert "ADOPT WITHOUT QUALIFICATION EVIDENCE" in result.stdout


def test_active_legacy_numbered_finding_cannot_escape_required_fields():
    report = textwrap.dedent(
        """
        # Report
        ## Active Findings
        ### [#1] [HIGH] Legacy numbered active finding
        - **Category**: CONFIGURATION
        """
    )
    result = _run(report)
    assert result.returncode == 1
    assert "MISSING VERDICT" in result.stdout
    assert "MISSING QUALIFICATION" in result.stdout
    assert "MISSING VERIFIED" in result.stdout
    assert "MISSING REQUIRED FIELD" in result.stdout


@pytest.mark.parametrize(
    "verified",
    (
        "no — not checked",
        "pending — source still changing",
        "yes",
        "unknown — no evidence",
        "maybe",
        "false — no evidence",
        "FAILED — could not read",
        "not-applicable — not checked",
        "yes: source read",
        "yes, source read",
    ),
)
def test_verified_field_requires_affirmative_evidence(verified: str):
    report = _finding(
        "- **Verdict**: REJECT",
        "- **Qualification**: not-applicable — no runtime change",
        f"- **Verified**: {verified}",
    )
    result = _run(report)
    assert result.returncode == 1
    assert "INVALID VERIFIED" in result.stdout


@pytest.mark.parametrize(
    ("verdict", "qualification"),
    (
        ("DEFER", "pending — wait for upstream"),
        ("DEFER", "FAILED — probe exited 1"),
        ("REJECT", "unverified — no source read"),
        ("REJECT", "PASSED — false exited 1"),
        ("ADOPT", "PASSED — pytest exited 1"),
    ),
)
def test_terminal_verdicts_reject_pending_or_failed_evidence(
    verdict: str, qualification: str
):
    trigger = "- **Trigger**: issue #123 closes" if verdict == "DEFER" else ""
    report = _finding(
        f"- **Verdict**: {verdict}",
        trigger,
        f"- **Qualification**: {qualification}",
        "- **Verified**: yes — source read",
    )
    result = _run(report)
    assert result.returncode == 1


def test_adopt_allows_an_expected_nonzero_reproduction_inside_passing_evidence():
    report = _finding(
        "- **Verdict**: ADOPT",
        "- **Qualification**: PASSED — reproduced the defect: negative control rc=1 was expected; fixed control returned 0",
        "- **Verified**: yes — both fixture outcomes were re-read",
    )
    result = _run(report)
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    "qualification",
    (
        "PASSED — pytest failed",
        "PASSED — tests pending",
        "PASSED — reproduced a fixture; integration exited 7 unexpectedly",
        "PASSED — negative control rc=1 was expected",
    ),
)
def test_adopt_rejects_contradictory_or_unclosed_negative_evidence(
    qualification: str,
):
    report = _finding(
        "- **Verdict**: ADOPT",
        f"- **Qualification**: {qualification}",
        "- **Verified**: yes — both fixture outcomes were re-read",
    )
    result = _run(report)
    assert result.returncode == 1
    assert "ADOPT WITHOUT QUALIFICATION EVIDENCE" in result.stdout


@pytest.mark.parametrize(
    "qualification",
    (
        "PASSED — trust me",
        "PASSED — command completed",
    ),
)
def test_adopt_requires_an_explicit_success_result(qualification: str):
    report = _finding(
        "- **Verdict**: ADOPT",
        f"- **Qualification**: {qualification}",
        "- **Verified**: yes — source and result were re-read",
    )
    result = _run(report)
    assert result.returncode == 1
    assert "ADOPT WITHOUT QUALIFICATION EVIDENCE" in result.stdout


@pytest.mark.parametrize(
    "verified",
    (
        "yes — no evidence",
        "yes — pending verification",
        "yes — unverified claim",
    ),
)
def test_verified_rejects_explicitly_absent_or_pending_evidence(verified: str):
    report = _finding(
        "- **Verdict**: REJECT",
        "- **Qualification**: not-applicable — no local edit applies",
        f"- **Verified**: {verified}",
    )
    result = _run(report)
    assert result.returncode == 1
    assert "INVALID VERIFIED" in result.stdout


@pytest.mark.parametrize(
    ("heading", "expected"),
    (
        ("### [2026-08-12] Mutation fixture", "MISSING SEVERITY"),
        ("### [2026-08-12] [CRITICAL] Mutation fixture", "INVALID SEVERITY"),
        ("### [2026-08-12 [HIGH] Mutation fixture", "MALFORMED FINDING HEADERS"),
        ("### [2026-08-12] [HIGH] ", "MALFORMED FINDING HEADERS"),
    ),
)
def test_finding_heading_severity_and_syntax_fail_closed(heading: str, expected: str):
    report = _finding(
        "- **Verdict**: REJECT",
        "- **Qualification**: not-applicable — no local edit applies",
        "- **Verified**: yes — source was re-read",
    ).replace("### [2026-08-12] [HIGH] Mutation fixture", heading)
    result = _run(report)
    assert result.returncode == 1
    assert expected in result.stdout


def test_indented_active_finding_is_parsed_not_silently_ignored():
    report = QUALIFY_REPORT.replace(
        "### [2026-08-12] [HIGH]", " ### [2026-08-12] [HIGH]", 1
    )
    result = _run(report)
    assert result.returncode == 1
    assert "UNRESOLVED QUALIFICATION" in result.stdout


@pytest.mark.parametrize("trigger", ("maybe later", "eventually", "TBD", "later"))
def test_defer_rejects_vague_trigger_placeholders(trigger: str):
    report = _finding(
        "- **Verdict**: DEFER",
        f"- **Trigger**: {trigger}",
        "- **Qualification**: not-applicable — upstream capability is absent",
        "- **Verified**: yes — issue state was re-read",
    )
    result = _run(report)
    assert result.returncode == 1
    assert "DEFER WITHOUT TRIGGER" in result.stdout


def test_adoption_metric_includes_recent_archived_terminal_findings():
    report = textwrap.dedent(
        """
        # Report
        ## Active Findings
        ### [2026-08-12] [LOW] Active rejection
        - **Category**: TRAINING
        - **Source**: https://example.test/rejection
        - **Baseline ref**: docs/current.md section 1
        - **What changed**: No relevant capability changed.
        - **Recommended edit**: Make no local change.
        - **Verdict**: REJECT
        - **Qualification**: not-applicable — no edit proposed
        - **Verified**: yes — source read
        ## Archived
        ### [2026-08-11] [MEDIUM] Recently adopted feature
        - **Category**: NEW_FEATURE
        - **Source**: https://example.test/adoption
        - **Baseline ref**: settings.json feature
        - **What changed**: The feature became available.
        - **Recommended edit**: Enable the qualified feature.
        - **Verdict**: ADOPT
        - **Qualification**: PASSED — pytest returned 0 with 4 passed
        - **Verified**: yes — target re-read
        """
    )
    result = _run(report, json_output=True)
    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["adoption"] == {
        "opportunities": 1,
        "adopted": 1,
    }


def test_adoption_metric_excludes_future_dated_findings():
    report = VALID_REPORT.replace("2026-08-12", "2027-08-12").replace(
        "2026-07-01", "2025-01-01"
    )
    result = _run(report, json_output=True)
    assert result.returncode == 0, result.stdout
    assert json.loads(result.stdout)["adoption"] == {
        "opportunities": 0,
        "adopted": 0,
    }


@pytest.mark.parametrize(
    "raw",
    (
        "~~DEFER~~ → **ADOPT**",
        "ADOPT — retire DEFER",
        "REJECT — do not RECOMMEND",
    ),
)
def test_ambiguous_or_illegal_verdict_mutations_are_not_parsed_as_valid(raw: str):
    assert rl._verdict_word(raw) is None


def test_json_mode_carries_all_blockers_and_the_same_exit_code():
    report = _finding(
        "- **Verdict**: DOCUMENT",
        "- **Qualification**: not-applicable — no runtime change",
    )
    result = _run(report, json_output=True)
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert len(payload["invalid_verdict"]) == 1
    assert len(payload["missing_verified"]) == 1
    assert payload["valid"] is False
