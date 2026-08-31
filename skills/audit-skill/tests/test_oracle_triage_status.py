"""Tests for the ``triage_status`` schema field (added 2026-05-25).

The triage_status field is the structural fix for the
"stale-finding-survives-into-next-campaign" pattern: during the
2026-05-25 triage of 25 [unverified] Phase 2 findings, 21 were STALE
(already addressed) and 4 were DEFER (real but not runtime-blocking),
but the YAML had no record of it. Without machine-readable triage
state, the next campaign would re-surface all 25.

Tests in this file pin three contracts:
  1. The Finding dataclass round-trips triage_status through
     YAML (load → dump → load preserves the field).
  2. act_on filters out closed-status findings BEFORE reverify
     (operator's explicit close beats any later reverify call).
  3. is_actionable() returns True only for empty / "open".

Tests use the in-tree fixtures and real reverify behavior — no mocks
(per tdd-quality rules 1 + Mock assertion gate).
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


def test_triage_status_valid_values():
    """Whitelist enforcement: only the 6 documented statuses are accepted."""
    Finding, Reproducer, TRIAGE_STATUSES, *_ = _load_oracle()
    assert set(TRIAGE_STATUSES) == {
        "", "open", "STALE", "FIXED", "FALSE_POSITIVE", "DEFER",
    }, f"TRIAGE_STATUSES drifted: {TRIAGE_STATUSES}"


def test_triage_status_rejects_unknown(tmp_path):
    """Constructing a Finding with an unknown status raises ValueError.

    The reproducer field's strict-whitelist pattern (lines 70-73 of
    finding.py) extends to triage_status."""
    Finding, Reproducer, *_ = _load_oracle()
    rep = Reproducer(type="manual", description="x")
    try:
        Finding(
            skill="x", code="T1", severity="drift", label="behavior-fix",
            description="d", reproducer=rep, triage_status="MAYBE-LATER",
        )
    except ValueError as e:
        assert "MAYBE-LATER" in str(e)
        return
    raise AssertionError("expected ValueError on unknown triage_status")


def test_is_actionable_only_for_open_or_empty():
    """is_actionable() is the contract act_on relies on. Returns True
    iff the operator has not closed the finding."""
    Finding, Reproducer, *_ = _load_oracle()
    rep = Reproducer(type="manual", description="x")
    base = dict(
        skill="x", code="T1", severity="drift", label="behavior-fix",
        description="d", reproducer=rep,
    )
    assert Finding(**base).is_actionable()                                  # default ""
    assert Finding(**base, triage_status="open").is_actionable()
    assert not Finding(**base, triage_status="STALE").is_actionable()
    assert not Finding(**base, triage_status="FIXED").is_actionable()
    assert not Finding(**base, triage_status="FALSE_POSITIVE").is_actionable()
    assert not Finding(**base, triage_status="DEFER").is_actionable()


def test_act_on_skips_closed_findings_before_reverify(tmp_path, monkeypatch):
    """The central contract: a finding marked triage_status=STALE is
    NEVER fed through reverify — it goes to triage_filtered. This
    means the operator's close takes precedence over the predicate
    (which might still fire if the underlying file existed before
    the operator's close decision)."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    Finding, Reproducer, _, _, act_on, _ = _load_oracle()

    # Set up a file that WOULD make a phantom-citation reproducer fire.
    target = tmp_path / "skill.md"
    target.write_text("cite: references/foo.md", encoding="utf-8")

    findings = [
        # Closed via triage; predicate would fire (foo.md doesn't exist)
        # but we MUST NOT run reverify on it.
        Finding(
            skill="example", code="H1", severity="drift", label="behavior-fix",
            description="closed by operator",
            reproducer=Reproducer(type="file_missing", path=str(tmp_path / "references" / "foo.md")),
            triage_status="STALE", triage_note="operator decided",
        ),
        # Open: predicate fires, should appear in worklist.
        Finding(
            skill="example", code="H1", severity="drift", label="behavior-fix",
            description="actually broken",
            reproducer=Reproducer(type="file_missing", path=str(tmp_path / "references" / "bar.md")),
        ),
    ]
    report = act_on(findings, tmp_path)
    # The STALE-triaged finding goes to triage_filtered, NOT to stale
    # (since stale is the reverify-result-STALE bucket).
    assert len(report.triage_filtered) == 1, (
        f"closed finding should be in triage_filtered; got {len(report.triage_filtered)}"
    )
    assert report.triage_filtered[0].description == "closed by operator"
    assert len(report.worklist) == 1
    assert report.worklist[0].description == "actually broken"


def test_act_on_filters_each_closed_status(tmp_path, monkeypatch):
    """Each of STALE / FIXED / FALSE_POSITIVE / DEFER filters identically."""
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    Finding, Reproducer, _, _, act_on, _ = _load_oracle()

    def mk(status):
        return Finding(
            skill="example", code="H1", severity="drift", label="behavior-fix",
            description=f"finding-with-{status}",
            reproducer=Reproducer(type="file_missing", path=str(tmp_path / "nope.md")),
            triage_status=status,
        )

    findings = [mk("STALE"), mk("FIXED"), mk("FALSE_POSITIVE"), mk("DEFER")]
    report = act_on(findings, tmp_path)
    assert len(report.triage_filtered) == 4
    assert len(report.worklist) == 0


def test_triage_status_roundtrip_through_yaml(tmp_path):
    """Roundtrip property (per tdd-quality.md rule 6): load(dump(F)) preserves
    triage_status and triage_note exactly. Without this, the operator's
    close vanishes on the next tracker write — the exact failure mode the
    schema was added to prevent."""
    Finding, Reproducer, _, load_findings, _, _to_yaml = _load_oracle()
    findings = [
        Finding(
            skill="X", code="D2", severity="drift", label="behavior-fix",
            description="needs note", reproducer=Reproducer(type="manual", description="m"),
            triage_status="DEFER", triage_note="real but deferred to wave 8",
        ),
        Finding(
            skill="Y", code="A1", severity="info", label="doc-fix",
            description="actionable", reproducer=Reproducer(type="manual", description="m"),
        ),
    ]
    yaml_path = tmp_path / "f.yaml"
    yaml_path.write_text(_to_yaml(findings), encoding="utf-8")
    loaded = load_findings(yaml_path)
    assert len(loaded) == 2
    assert loaded[0].triage_status == "DEFER"
    assert loaded[0].triage_note == "real but deferred to wave 8"
    assert loaded[1].triage_status == ""  # default preserved
    assert loaded[1].triage_note == ""


def test_finding_default_triage_status_is_empty():
    """The default must be "" so existing findings (without an explicit
    field in their YAML) behave as actionable. Any other default would
    silently re-open closed findings during YAML round-trip."""
    Finding, Reproducer, *_ = _load_oracle()
    rep = Reproducer(type="manual", description="x")
    f = Finding(
        skill="x", code="T1", severity="drift", label="behavior-fix",
        description="d", reproducer=rep,
    )
    assert f.triage_status == ""
    assert f.triage_note == ""
    assert f.is_actionable()


def test_from_dict_coerces_unknown_triage_status(capsys):
    """File-loading path (from_dict) must NOT abort on an out-of-enum
    triage_status — it coerces to "" (actionable: surfaces, never hides)
    and warns to stderr. Strict rejection stays in __post_init__ for
    direct construction (see test_triage_status_rejects_unknown).

    Regression guard for the 2026-06-16 incident: a prior
    audit-architecture-findings.yaml with triage_status: BLOCKED made
    `reverify` exit 2 at load, blackholing ALL gating until the file was
    hand-rewritten. One out-of-enum value must never blackhole the file."""
    Finding, Reproducer, *_ = _load_oracle()
    f = Finding.from_dict({
        "skill": "x", "code": "T1", "severity": "info", "label": "unverified",
        "description": "d", "reproducer": {"type": "manual", "description": "m"},
        "triage_status": "BLOCKED",
    })
    assert f.triage_status == ""          # coerced, not raised
    assert f.is_actionable()              # "" → actionable
    err = capsys.readouterr().err
    assert "BLOCKED" in err and "coercing" in err   # warned, not silent


def test_load_findings_survives_unknown_triage_status(tmp_path):
    """End-to-end: a YAML file with an out-of-enum triage_status loads
    (with a warning) instead of raising FindingsParseError — the exact
    path that aborted reverify on 2026-06-16."""
    Finding, Reproducer, _, load_findings, _, _ = _load_oracle()
    yaml_path = tmp_path / "bad.yaml"
    yaml_path.write_text(
        "findings:\n"
        "  - skill: x\n"
        "    code: T1\n"
        "    severity: info\n"
        "    label: unverified\n"
        "    description: d\n"
        "    triage_status: DIAGNOSED\n"
        "    reproducer:\n"
        "      type: manual\n"
        "      description: m\n",
        encoding="utf-8",
    )
    loaded = load_findings(yaml_path)     # must NOT raise
    assert len(loaded) == 1
    assert loaded[0].triage_status == ""  # coerced on the file-load path
