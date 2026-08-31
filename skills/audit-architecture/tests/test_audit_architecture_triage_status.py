"""Tests for triage_status schema field adapted for audit-architecture.

Adapted from skills/audit-skill/tests/test_oracle_triage_status.py.

Pins the triage_status contracts for architecture findings:
  1. TRIAGE_STATUSES whitelist is exactly the 6 documented values.
  2. Unknown status raises ValueError.
  3. is_actionable() returns True only for "" and "open".
  4. act_on skips closed-status findings BEFORE reverify
     (operator's close beats any later reproducer run).
  5. act_on filters all four closed statuses.
  6. triage_status round-trips through YAML (load → _to_yaml → load).
  7. Default triage_status is "".

Architecture codes used: R3 (bash / python), C2 (grep_absent), D5 (file_missing).

Re-run:
    pytest skills/audit-architecture/tests/test_audit_architecture_triage_status.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load_oracle():
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for mod in (
        "oracle", "oracle.finding", "oracle.act_on", "oracle.reverify",
        "oracle.tracker", "oracle.trace",
    ):
        if mod in sys.modules:
            del sys.modules[mod]
    from oracle.finding import Finding, Reproducer, TRIAGE_STATUSES, load_findings  # noqa: E402
    from oracle.act_on import act_on  # noqa: E402
    from oracle.tracker import _to_yaml  # noqa: E402
    return Finding, Reproducer, TRIAGE_STATUSES, load_findings, act_on, _to_yaml


def test_triage_statuses_whitelist():
    """TRIAGE_STATUSES must contain exactly the 6 documented values."""
    Finding, Reproducer, TRIAGE_STATUSES, *_ = _load_oracle()
    assert set(TRIAGE_STATUSES) == {
        "", "open", "STALE", "FIXED", "FALSE_POSITIVE", "DEFER",
    }, f"TRIAGE_STATUSES drifted: {TRIAGE_STATUSES}"


def test_unknown_triage_status_raises_value_error(tmp_path):
    """Constructing a Finding with an undocumented status raises ValueError."""
    Finding, Reproducer, *_ = _load_oracle()
    rep = Reproducer(type="manual", description="x")
    try:
        Finding(
            skill="architecture-fixture", code="R3",
            severity="drift", label="behavior-fix",
            description="bad status test", reproducer=rep,
            triage_status="MAYBE-LATER",
        )
    except ValueError as e:
        assert "MAYBE-LATER" in str(e)
        return
    raise AssertionError("expected ValueError on unknown triage_status")


def test_is_actionable_only_for_open_or_empty():
    """is_actionable() is True only for "" and "open"."""
    Finding, Reproducer, *_ = _load_oracle()
    rep = Reproducer(type="manual", description="x")
    base = dict(
        skill="architecture-fixture", code="C2",
        severity="drift", label="behavior-fix",
        description="d", reproducer=rep,
    )
    assert Finding(**base).is_actionable()                          # default ""
    assert Finding(**base, triage_status="open").is_actionable()
    assert not Finding(**base, triage_status="STALE").is_actionable()
    assert not Finding(**base, triage_status="FIXED").is_actionable()
    assert not Finding(**base, triage_status="FALSE_POSITIVE").is_actionable()
    assert not Finding(**base, triage_status="DEFER").is_actionable()


def test_act_on_skips_closed_findings_before_reverify(tmp_path, monkeypatch):
    """Closed findings go to triage_filtered WITHOUT running reverify.
    Open findings (where predicate still fires) go to worklist."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    Finding, Reproducer, _, _, act_on, _ = _load_oracle()

    findings = [
        # Closed: operator triaged as STALE — must skip reverify
        Finding(
            skill="architecture-fixture", code="D5",
            severity="info", label="doc-fix",
            description="closed by operator — phantom server already removed",
            reproducer=Reproducer(
                type="file_missing",
                path=str(tmp_path / "references" / "phantom.md"),
            ),
            triage_status="STALE", triage_note="resolved in prior sprint",
        ),
        # Open: file still missing → STILL-FIRES → worklist
        Finding(
            skill="architecture-fixture", code="R3",
            severity="drift", label="behavior-fix",
            description="server script still missing",
            reproducer=Reproducer(
                type="file_missing",
                path=str(tmp_path / "server" / "missing.py"),
            ),
        ),
    ]
    report = act_on(findings, tmp_path)
    assert len(report.triage_filtered) == 1, (
        f"closed finding should be in triage_filtered; got {len(report.triage_filtered)}"
    )
    assert report.triage_filtered[0].description == "closed by operator — phantom server already removed"
    assert len(report.worklist) == 1
    assert report.worklist[0].description == "server script still missing"


def test_act_on_filters_all_four_closed_statuses(tmp_path, monkeypatch):
    """Each of STALE / FIXED / FALSE_POSITIVE / DEFER is filtered."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    Finding, Reproducer, _, _, act_on, _ = _load_oracle()

    def mk(status):
        return Finding(
            skill="architecture-fixture", code="C2",
            severity="drift", label="behavior-fix",
            description=f"finding-with-{status}",
            reproducer=Reproducer(
                type="file_missing",
                path=str(tmp_path / f"nope-{status}.json"),
            ),
            triage_status=status,
        )

    findings = [mk("STALE"), mk("FIXED"), mk("FALSE_POSITIVE"), mk("DEFER")]
    report = act_on(findings, tmp_path)
    assert len(report.triage_filtered) == 4
    assert len(report.worklist) == 0


def test_triage_status_roundtrip_through_yaml(tmp_path):
    """load(dump(F)) preserves triage_status and triage_note exactly."""
    Finding, Reproducer, _, load_findings, _, _to_yaml = _load_oracle()
    findings = [
        Finding(
            skill="architecture-fixture", code="D5",
            severity="info", label="doc-fix",
            description="undocumented server — deferred",
            reproducer=Reproducer(type="manual", description="manual check"),
            triage_status="DEFER", triage_note="real but deferred to wave 8",
        ),
        Finding(
            skill="architecture-fixture", code="R3",
            severity="drift", label="behavior-fix",
            description="invalid JSON — actionable",
            reproducer=Reproducer(type="manual", description="manual check"),
        ),
    ]
    yaml_path = tmp_path / "f.yaml"
    yaml_path.write_text(_to_yaml(findings), encoding="utf-8")
    loaded = load_findings(yaml_path)
    assert len(loaded) == 2
    assert loaded[0].triage_status == "DEFER"
    assert loaded[0].triage_note == "real but deferred to wave 8"
    assert loaded[1].triage_status == ""    # default preserved
    assert loaded[1].triage_note == ""


def test_finding_default_triage_status_is_empty():
    """Default triage_status must be "" so existing findings are actionable."""
    Finding, Reproducer, *_ = _load_oracle()
    rep = Reproducer(type="manual", description="x")
    f = Finding(
        skill="architecture-fixture", code="C2",
        severity="drift", label="behavior-fix",
        description="d", reproducer=rep,
    )
    assert f.triage_status == ""
    assert f.triage_note == ""
    assert f.is_actionable()
