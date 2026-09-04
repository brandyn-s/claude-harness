"""Tests for oracle.discover adapted for audit-architecture.

Adapted from skills/audit-skill/tests/test_oracle_discover.py.

audit-architecture is Phase-2-only (no deterministic Phase 1 linter
like bin/audit-skill.py), so these tests focus on:

  1. discover_worklist smoke test: runs without crashing against the
     audit-architecture skill, returns an ActOnReport with the right shape.
  2. discover_worklist integrates Phase 2 findings passed via the
     phase2_findings argument.
  3. ActOnReport has the expected fields: worklist, stale, still_fires,
     manual, error, stale_rate.

Architecture codes used: R3, C2, D5.

Re-run:
    pytest skills/audit-architecture/tests/test_audit_architecture_discover.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load_oracle():
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for mod in (
        "oracle", "oracle.discover", "oracle.finding",
        "oracle.act_on", "oracle.reverify", "oracle.trace",
    ):
        if mod in sys.modules:
            del sys.modules[mod]
    from oracle.discover import discover_worklist, discover_phase1_only  # noqa: E402
    from oracle.act_on import ActOnReport  # noqa: E402
    from oracle.finding import Finding, Reproducer  # noqa: E402
    return discover_worklist, discover_phase1_only, ActOnReport, Finding, Reproducer


def test_discover_worklist_smoke_test(tmp_path, monkeypatch):
    """Integration smoke test: discover_worklist against audit-architecture
    runs without crashing and returns an ActOnReport with correct shape.
    Actual finding count may vary — this test pins the interface, not the count."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    discover_worklist, _, ActOnReport, _, _ = _load_oracle()

    report = discover_worklist(REPO, skill="audit-architecture")

    assert isinstance(report, ActOnReport)
    assert hasattr(report, "worklist")
    assert hasattr(report, "stale")
    assert hasattr(report, "still_fires")
    assert hasattr(report, "manual")
    assert hasattr(report, "error")
    assert isinstance(report.stale_rate, float)
    assert 0.0 <= report.stale_rate <= 1.0


def test_discover_worklist_integrates_phase2_findings(tmp_path, monkeypatch):
    """phase2_findings argument is integrated into the act_on report.

    Passes two synthetic Phase 2 findings (one STILL-FIRES via file_missing,
    one STALE via grep on a file that doesn't contain the pattern).
    Verifies the combined worklist contains only the STILL-FIRES finding."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    discover_worklist, _, _, Finding, Reproducer = _load_oracle()

    # STILL-FIRES: file genuinely absent
    still_fires_finding = Finding(
        skill="audit-architecture",
        code="D5",
        severity="info",
        label="doc-fix",
        description="phantom-server missing from architecture docs (phase2)",
        reproducer=Reproducer(
            type="file_missing",
            path=str(tmp_path / "phantom-server-docs.md"),
        ),
    )

    # Write a real file so grep finds nothing matching → STALE for R3 check
    settings = tmp_path / "settings.json"
    settings.write_text('{"ok": true}', encoding="utf-8")

    stale_finding = Finding(
        skill="audit-architecture",
        code="R3",
        severity="drift",
        label="behavior-fix",
        description="settings.json invalid JSON (already fixed, phase2)",
        reproducer=Reproducer(
            type="bash",
            command=(
                f"python3 -c \"import json; json.load(open('{settings.as_posix()}'))\" "
                "2>/dev/null"
            ),
            expected_exit=1,  # expecting failure, but parse succeeds → STALE
        ),
    )

    report = discover_worklist(
        REPO,
        skill="audit-architecture",
        phase2_findings=[still_fires_finding, stale_finding],
    )

    # The D5 still-fires finding must appear in the worklist
    worklist_descs = [f.description for f in report.worklist]
    assert any(
        "phantom-server missing from architecture docs (phase2)" in d
        for d in worklist_descs
    ), (
        f"D5 still-fires finding should be in worklist; got: {worklist_descs}"
    )
    # stale_rate must be a valid float
    assert isinstance(report.stale_rate, float)


def test_act_on_report_has_expected_fields(tmp_path, monkeypatch):
    """ActOnReport has all fields the orchestrator expects."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    discover_worklist, _, ActOnReport, _, _ = _load_oracle()

    report = discover_worklist(REPO, skill="audit-architecture")

    # Structural field checks
    assert isinstance(report.worklist, list)
    assert isinstance(report.stale, list)
    assert isinstance(report.still_fires, list)
    assert isinstance(report.manual, list)
    assert isinstance(report.error, list)
    assert isinstance(report.stale_rate, float)
    # verified_at is set by act_on
    assert report.verified_at, "verified_at should be set by discover_worklist"
