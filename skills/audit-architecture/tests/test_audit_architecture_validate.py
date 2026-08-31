"""Tests for oracle.validate adapted for audit-architecture.

Adapted from skills/audit-skill/tests/test_oracle_validate.py.

Pins schema enforcement at the fix-orchestrator boundary using
architecture-specific finding codes (R3, C2, D5):

  - reject_prose_input: .md files rejected
  - reject_manual_findings: type=manual rejected
  - reject_not_reverified: no trace record → rejected
  - reject_stale_record: trace older than TTL → rejected
  - accept_recent_verified_worklist: fresh trace → OK
  - format_rejections_groups_by_code
  - load_findings raises FindingsParseError on malformed YAML
  - load_findings handles empty findings list

Re-run:
    pytest skills/audit-architecture/tests/test_audit_architecture_validate.py -q
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load_oracle():
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for mod in ("oracle", "oracle.finding", "oracle.validate",
                "oracle.trace", "oracle.tracker"):
        if mod in sys.modules:
            del sys.modules[mod]
    from oracle import validate as v_mod  # noqa: E402
    from oracle import finding as f_mod  # noqa: E402
    from oracle import trace as t_mod  # noqa: E402
    from oracle.tracker import _to_yaml  # noqa: E402
    return v_mod, f_mod, t_mod, _to_yaml


def test_reject_prose_input(tmp_path):
    """Raw markdown tracker is rejected at the boundary."""
    v_mod, _, _, _ = _load_oracle()
    md_path = tmp_path / "architecture-tracker.md"
    md_path.write_text("# architecture tracker prose\n", encoding="utf-8")
    rejections = v_mod.validate_for_dispatch(md_path)
    assert len(rejections) == 1
    assert rejections[0].code == "REJECT_PROSE_INPUT"
    assert "markdown tracker" in rejections[0].reason


def test_reject_manual_findings(tmp_path, monkeypatch):
    """Findings with type=manual are rejected — oracle has not verified them."""
    v_mod, f_mod, _, to_yaml = _load_oracle()
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))

    findings = [
        f_mod.Finding(
            skill="architecture-fixture",
            code="C2",
            severity="drift",
            label="behavior-fix",
            description="routing rule gap — manual check needed",
            reproducer=f_mod.Reproducer(type="manual", description="check routing"),
        ),
    ]
    worklist = tmp_path / "worklist.yaml"
    worklist.write_text(to_yaml(findings), encoding="utf-8")

    rejections = v_mod.validate_for_dispatch(worklist)
    assert any(r.code == "REJECT_NO_REPRODUCER" for r in rejections)


def test_reject_not_reverified(tmp_path, monkeypatch):
    """Findings without a trace record (act_on never ran) are rejected."""
    v_mod, f_mod, _, to_yaml = _load_oracle()
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "no-trace.jsonl"))

    findings = [
        f_mod.Finding(
            skill="architecture-fixture",
            code="R3",
            severity="drift",
            label="behavior-fix",
            description="settings.json is not valid JSON",
            reproducer=f_mod.Reproducer(
                type="grep", command="grep -q 'bad' settings.json"
            ),
        ),
    ]
    worklist = tmp_path / "worklist.yaml"
    worklist.write_text(to_yaml(findings), encoding="utf-8")

    rejections = v_mod.validate_for_dispatch(worklist)
    assert any(r.code == "REJECT_NOT_REVERIFIED" for r in rejections)


def test_reject_stale_record(tmp_path, monkeypatch):
    """Worklist with trace records older than TTL is rejected."""
    v_mod, f_mod, t_mod, to_yaml = _load_oracle()
    trace_file = tmp_path / "trace.jsonl"
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(trace_file))

    findings = [
        f_mod.Finding(
            skill="architecture-fixture",
            code="D5",
            severity="info",
            label="doc-fix",
            description="phantom-server undocumented in ARCHITECTURE.md",
            reproducer=f_mod.Reproducer(
                type="grep_absent",
                command="grep -q 'phantom-server' ARCHITECTURE.md",
            ),
        ),
    ]
    worklist = tmp_path / "worklist.yaml"
    worklist.write_text(to_yaml(findings), encoding="utf-8")

    # Write an OLD trace record (1 hour ago — beyond the 30-min default TTL)
    fid = t_mod.finding_id(
        findings[0].skill, findings[0].code, findings[0].description
    )
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(
        timespec="seconds"
    )
    rec = {
        "ts": old_ts,
        "layer": "A",
        "finding_id": fid,
        "skill": findings[0].skill,
        "verdict": "STILL-FIRES",
        "evidence": "stale record for test",
        "procedure_version": "test",
        "model_version": None,
        "latency_ms": 5,
        "cost_usd": None,
        "input": {"reproducer_type": "grep_absent", "reproducer_command_sha": "deadbeef"},
        "schema_version": "1.0",
    }
    trace_file.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    rejections = v_mod.validate_for_dispatch(worklist)
    assert any(r.code == "REJECT_STALE_RECORD" for r in rejections)


def test_accept_recent_verified_worklist(tmp_path, monkeypatch):
    """A worklist with a fresh trace record passes validation."""
    v_mod, f_mod, t_mod, to_yaml = _load_oracle()
    trace_file = tmp_path / "trace.jsonl"
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(trace_file))

    findings = [
        f_mod.Finding(
            skill="architecture-fixture",
            code="R3",
            severity="drift",
            label="behavior-fix",
            description="settings.json is not valid JSON",
            reproducer=f_mod.Reproducer(
                type="grep", command="grep -q 'bad' settings.json"
            ),
        ),
    ]
    worklist = tmp_path / "worklist.yaml"
    worklist.write_text(to_yaml(findings), encoding="utf-8")

    fid = t_mod.finding_id(
        findings[0].skill, findings[0].code, findings[0].description
    )
    fresh_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rec = {
        "ts": fresh_ts,
        "layer": "A",
        "finding_id": fid,
        "skill": findings[0].skill,
        "verdict": "STILL-FIRES",
        "evidence": "fresh record for test",
        "procedure_version": "test",
        "model_version": None,
        "latency_ms": 5,
        "cost_usd": None,
        "input": {"reproducer_type": "grep", "reproducer_command_sha": "deadbeef"},
        "schema_version": "1.0",
    }
    trace_file.write_text(json.dumps(rec) + "\n", encoding="utf-8")

    rejections = v_mod.validate_for_dispatch(worklist)
    assert not rejections, f"expected OK, got: {[str(r) for r in rejections]}"


def test_format_rejections_groups_by_code():
    """format_rejections groups rejection messages by code."""
    v_mod, _, _, _ = _load_oracle()
    rejections = [
        v_mod.Rejection("REJECT_NO_REPRODUCER", "fid1", "architecture-fixture", "manual"),
        v_mod.Rejection("REJECT_NO_REPRODUCER", "fid2", "architecture-fixture", "manual"),
        v_mod.Rejection("REJECT_STALE_RECORD", "fid3", "architecture-fixture", "old"),
    ]
    out = v_mod.format_rejections(rejections)
    assert "REJECTED (3" in out
    assert "REJECT_NO_REPRODUCER (2)" in out
    assert "REJECT_STALE_RECORD (1)" in out


def test_load_findings_raises_on_malformed_yaml(tmp_path):
    """Malformed YAML raises FindingsParseError (not raw TypeError/KeyError)."""
    _, f_mod, _, _ = _load_oracle()
    p = tmp_path / "bad.yaml"
    p.write_text("findings:\n  - skill: x\n   code: bad-indent\n", encoding="utf-8")
    try:
        f_mod.load_findings(p)
    except f_mod.FindingsParseError as e:
        assert "bad.yaml" in str(e) or "missing or has a malformed field" in str(e)
        return
    raise AssertionError("expected FindingsParseError")


def test_load_findings_handles_empty_list(tmp_path):
    """load_findings with an empty findings list returns []."""
    _, f_mod, _, _ = _load_oracle()
    p = tmp_path / "empty.yaml"
    p.write_text("findings: []\n", encoding="utf-8")
    fs = f_mod.load_findings(p)
    assert fs == []
