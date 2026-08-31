"""Tests for oracle.validate — schema enforcement at the
fix-orchestrator boundary. Root-cause fix for causes 3 + 6.

The gate is mandatory for the orchestrator; these tests pin its
behavior so future changes can't silently re-introduce the "raw
tracker dispatched to fix-agents" pattern.
"""
from __future__ import annotations

import importlib.util
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
    """Cause 6 fix: raw markdown tracker is rejected at the boundary."""
    v_mod, _, _, _ = _load_oracle()
    md_path = tmp_path / "tracker.md"
    md_path.write_text("# tracker prose\n", encoding="utf-8")
    rejections = v_mod.validate_for_dispatch(md_path)
    assert len(rejections) == 1
    assert rejections[0].code == "REJECT_PROSE_INPUT"
    assert "markdown tracker" in rejections[0].reason


def test_reject_manual_findings(tmp_path, monkeypatch):
    """Cause 6 fix: findings with type=manual are rejected — the
    oracle has not made a verification claim, so dispatching a fix
    against them is undefined."""
    v_mod, f_mod, _, to_yaml = _load_oracle()
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))

    findings = [
        f_mod.Finding(
            skill="example",
            code="X1",
            severity="info",
            label="unverified",
            description="vague claim",
            reproducer=f_mod.Reproducer(type="manual", description="prose"),
        ),
    ]
    worklist = tmp_path / "worklist.yaml"
    worklist.write_text(to_yaml(findings), encoding="utf-8")

    rejections = v_mod.validate_for_dispatch(worklist)
    assert any(r.code == "REJECT_NO_REPRODUCER" for r in rejections)


def test_reject_not_reverified(tmp_path, monkeypatch):
    """Cause 3 fix: findings without a trace record (act_on never
    ran) are rejected."""
    v_mod, f_mod, _, to_yaml = _load_oracle()
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "no-trace.jsonl"))

    findings = [
        f_mod.Finding(
            skill="example",
            code="H1",
            severity="drift",
            label="behavior-fix",
            description="bug",
            reproducer=f_mod.Reproducer(type="grep", command="grep -q foo file"),
        ),
    ]
    worklist = tmp_path / "worklist.yaml"
    worklist.write_text(to_yaml(findings), encoding="utf-8")

    rejections = v_mod.validate_for_dispatch(worklist)
    assert any(r.code == "REJECT_NOT_REVERIFIED" for r in rejections)


def test_reject_stale_record(tmp_path, monkeypatch):
    """Cause 4 fix: worklists with trace records older than the TTL
    are rejected. The orchestrator must re-run act_on."""
    v_mod, f_mod, t_mod, to_yaml = _load_oracle()
    trace_file = tmp_path / "trace.jsonl"
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(trace_file))

    findings = [
        f_mod.Finding(
            skill="example",
            code="H1",
            severity="drift",
            label="behavior-fix",
            description="bug",
            reproducer=f_mod.Reproducer(type="grep", command="grep -q foo file"),
        ),
    ]
    worklist = tmp_path / "worklist.yaml"
    worklist.write_text(to_yaml(findings), encoding="utf-8")

    # Write an OLD trace record (1 hour ago — beyond the 30-min default TTL).
    fid = t_mod.finding_id(findings[0].skill, findings[0].code, findings[0].description)
    old_ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
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
        "input": {"reproducer_type": "grep", "reproducer_command_sha": "deadbeef"},
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
            skill="example",
            code="H1",
            severity="drift",
            label="behavior-fix",
            description="bug",
            reproducer=f_mod.Reproducer(type="grep", command="grep -q foo file"),
        ),
    ]
    worklist = tmp_path / "worklist.yaml"
    worklist.write_text(to_yaml(findings), encoding="utf-8")

    fid = t_mod.finding_id(findings[0].skill, findings[0].code, findings[0].description)
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


def test_reject_nonspecific_reproducer(tmp_path, monkeypatch):
    """Specificity guard (Phase 1): a vacuous reproducer (`grep -q .`)
    fires regardless of content, so its STILL-FIRES verdict certifies
    nothing. validate_for_dispatch must reject it — closing the
    proposer-grades-its-own-homework hole. Static layer catches this one,
    so no repo_root is needed."""
    v_mod, f_mod, _, to_yaml = _load_oracle()
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    findings = [
        f_mod.Finding(
            skill="example", code="H1", severity="drift", label="behavior-fix",
            description="vacuous predicate",
            reproducer=f_mod.Reproducer(type="grep", command="grep -q . SKILL.md"),
        ),
    ]
    worklist = tmp_path / "worklist.yaml"
    worklist.write_text(to_yaml(findings), encoding="utf-8")
    rejections = v_mod.validate_for_dispatch(worklist)
    assert any(r.code == "REJECT_NONSPECIFIC_REPRODUCER" for r in rejections), \
        f"expected REJECT_NONSPECIFIC_REPRODUCER, got {[r.code for r in rejections]}"


def test_specific_reproducer_not_flagged_by_guard(tmp_path, monkeypatch):
    """Regression guard against over-rejection: a specific reproducer
    (grep for a real token) must NOT trip REJECT_NONSPECIFIC_REPRODUCER."""
    v_mod, f_mod, _, to_yaml = _load_oracle()
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    findings = [
        f_mod.Finding(
            skill="example", code="H1", severity="drift", label="behavior-fix",
            description="specific predicate",
            reproducer=f_mod.Reproducer(type="grep", command="grep -q 'SPECIFIC_TOKEN_ABC' file"),
        ),
    ]
    worklist = tmp_path / "worklist.yaml"
    worklist.write_text(to_yaml(findings), encoding="utf-8")
    rejections = v_mod.validate_for_dispatch(worklist)
    assert not any(r.code == "REJECT_NONSPECIFIC_REPRODUCER" for r in rejections)


def test_reject_unverified_verdict(tmp_path, monkeypatch):
    """Verdict-blind-gate fix: a FRESH Layer-A record whose verdict is ERROR
    (broken instrument) must be rejected — the reproducer never demonstrated the
    bug, so the finding is not dispatchable. Previously only freshness/presence
    were checked and an ERROR-verdict finding sailed through."""
    v_mod, f_mod, t_mod, to_yaml = _load_oracle()
    trace_file = tmp_path / "trace.jsonl"
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(trace_file))
    findings = [
        f_mod.Finding(
            skill="example", code="H1", severity="drift", label="behavior-fix",
            description="bug",
            reproducer=f_mod.Reproducer(type="grep", command="grep -q 'REAL_TOKEN_XYZ' file"),
        ),
    ]
    worklist = tmp_path / "worklist.yaml"
    worklist.write_text(to_yaml(findings), encoding="utf-8")
    fid = t_mod.finding_id(findings[0].skill, findings[0].code, findings[0].description)
    fresh_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rec = {
        "ts": fresh_ts, "layer": "A", "finding_id": fid, "skill": findings[0].skill,
        "verdict": "ERROR", "evidence": "grep rc=2 (instrument failure)",
        "procedure_version": "test", "model_version": None, "latency_ms": 5,
        "cost_usd": None,
        "input": {"reproducer_type": "grep", "reproducer_command_sha": "deadbeef"},
        "schema_version": "1.0",
    }
    trace_file.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    rejections = v_mod.validate_for_dispatch(worklist)
    assert any(r.code == "REJECT_UNVERIFIED_VERDICT" for r in rejections), \
        f"expected REJECT_UNVERIFIED_VERDICT, got {[r.code for r in rejections]}"


def test_reject_nonspecific_python_reproducer(tmp_path, monkeypatch):
    """Specificity guard now covers type=python: a snippet that fires
    unconditionally (`raise SystemExit(1)`) certifies nothing. The grep/bash
    control-run can't cover python (a missing-file exception reads as a fire),
    so this is a static AST check in static_vacuity/_python_vacuous."""
    v_mod, f_mod, _, to_yaml = _load_oracle()
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    findings = [
        f_mod.Finding(
            skill="example", code="H1", severity="drift", label="behavior-fix",
            description="vacuous python predicate",
            reproducer=f_mod.Reproducer(type="python", command="raise SystemExit(1)"),
        ),
    ]
    worklist = tmp_path / "worklist.yaml"
    worklist.write_text(to_yaml(findings), encoding="utf-8")
    rejections = v_mod.validate_for_dispatch(worklist)
    assert any(r.code == "REJECT_NONSPECIFIC_REPRODUCER" for r in rejections), \
        f"expected REJECT_NONSPECIFIC_REPRODUCER, got {[r.code for r in rejections]}"


def test_specific_python_reproducer_not_flagged(tmp_path, monkeypatch):
    """Regression guard against over-rejection: a content-reading python
    reproducer (reads a file, conditional exit) must NOT be flagged vacuous."""
    v_mod, f_mod, _, to_yaml = _load_oracle()
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    findings = [
        f_mod.Finding(
            skill="example", code="H1", severity="drift", label="behavior-fix",
            description="specific python predicate",
            reproducer=f_mod.Reproducer(
                type="python",
                command="import sys\nsys.exit(0 if 'ok' in open('f').read() else 1)",
            ),
        ),
    ]
    worklist = tmp_path / "worklist.yaml"
    worklist.write_text(to_yaml(findings), encoding="utf-8")
    rejections = v_mod.validate_for_dispatch(worklist)
    assert not any(r.code == "REJECT_NONSPECIFIC_REPRODUCER" for r in rejections)


def test_format_rejections_groups_by_code():
    v_mod, _, _, _ = _load_oracle()
    rejections = [
        v_mod.Rejection("REJECT_NO_REPRODUCER", "fid1", "skill-a", "manual"),
        v_mod.Rejection("REJECT_NO_REPRODUCER", "fid2", "skill-b", "manual"),
        v_mod.Rejection("REJECT_STALE_RECORD", "fid3", "skill-c", "old"),
    ]
    out = v_mod.format_rejections(rejections)
    assert "REJECTED (3" in out
    assert "REJECT_NO_REPRODUCER (2)" in out
    assert "REJECT_STALE_RECORD (1)" in out


# ──────────────────────────────────────────────────────────────────
# FindingsParseError contract — surfaced by adversarial stress test
# (2026-05-26). Malformed YAML or schema-incomplete entries must NOT
# raise raw TypeError / KeyError; they must raise FindingsParseError
# with a human-readable message that the CLI translates into a clean
# stderr message + exit 2.
# ──────────────────────────────────────────────────────────────────

def test_load_findings_raises_on_malformed_yaml(tmp_path):
    _, f_mod, _, _ = _load_oracle()
    p = tmp_path / "bad.yaml"
    p.write_text("findings:\n  - skill: x\n   code: bad-indent\n", encoding="utf-8")
    try:
        f_mod.load_findings(p)
    except f_mod.FindingsParseError as e:
        assert "bad.yaml" in str(e) or "missing or has a malformed field" in str(e)
        return
    raise AssertionError("expected FindingsParseError")


def test_load_findings_raises_on_missing_required_fields(tmp_path):
    _, f_mod, _, _ = _load_oracle()
    p = tmp_path / "missing.yaml"
    # entry has no `reproducer` block; Reproducer(**{}) would TypeError
    p.write_text("findings:\n  - skill: x\n    code: X\n", encoding="utf-8")
    try:
        f_mod.load_findings(p)
    except f_mod.FindingsParseError as e:
        msg = str(e)
        assert "entry #0" in msg
        assert "skill='x'" in msg
        assert "Reproducer" in msg or "type" in msg
        return
    raise AssertionError("expected FindingsParseError")


def test_load_findings_empty_list_is_OK(tmp_path):
    _, f_mod, _, _ = _load_oracle()
    p = tmp_path / "empty.yaml"
    p.write_text("findings: []\n", encoding="utf-8")
    fs = f_mod.load_findings(p)
    assert fs == []


def test_load_findings_missing_findings_key_is_OK(tmp_path):
    _, f_mod, _, _ = _load_oracle()
    p = tmp_path / "no-findings.yaml"
    p.write_text("some_other_key: foo\n", encoding="utf-8")
    fs = f_mod.load_findings(p)
    assert fs == []


def test_load_findings_top_level_must_be_mapping(tmp_path):
    _, f_mod, _, _ = _load_oracle()
    p = tmp_path / "list-toplevel.json"
    # JSON list at top level is a schema error.
    p.write_text("[1, 2, 3]", encoding="utf-8")
    try:
        f_mod.load_findings(p)
    except f_mod.FindingsParseError as e:
        assert "mapping at top level" in str(e)
        return
    raise AssertionError("expected FindingsParseError")
