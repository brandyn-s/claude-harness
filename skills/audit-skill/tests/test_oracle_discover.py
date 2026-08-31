"""Tests for oracle.discover — root-cause fix for cause 1
(static tracker / live-tree mismatch).

The discover module replaces the "write a static tracker, read it
later" pattern with a single one-shot: Phase 1 lint + Layer A
reverify in one call. The worklist that comes out is already
verified and has fresh trace records.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def _load_oracle():
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for mod in ("oracle", "oracle.discover", "oracle.finding",
                 "oracle.act_on", "oracle.reverify", "oracle.trace"):
        if mod in sys.modules:
            del sys.modules[mod]
    from oracle.discover import (  # noqa: E402
        discover_phase1_only, discover_worklist, _phase1_reproducer,
    )
    return discover_phase1_only, discover_worklist, _phase1_reproducer


def test_phase1_reproducer_infers_for_h1():
    """H1 (phantom citation) → file_missing Reproducer."""
    _, _, infer = _load_oracle()
    r = infer("H1", "example", "cited references/missing-ref.md does not exist")
    assert r.type == "file_missing"
    assert "missing-ref.md" in r.path


def test_phase1_reproducer_infers_for_h4():
    """H4 (cross-skill citation broken) → file_missing for the
    target skill's reference."""
    _, _, infer = _load_oracle()
    r = infer("H4", "caller-skill",
              "cross-skill citation target-skill/references/foo.md does not exist")
    assert r.type == "file_missing"
    assert "target-skill/references/foo.md" in r.path


def test_phase1_reproducer_infers_for_t1():
    """T1 (phantom MCP tool) → grep on the skill dir. The grep
    command regex-escapes the hyphen for safety, so the literal
    match in the command will be ``mcp__code\\-graph__index_status``
    — this test accepts either form."""
    _, _, infer = _load_oracle()
    r = infer("T1", "example",
              "reference to known-phantom MCP tool 'mcp__code-graph__index_status'")
    assert r.type == "grep"
    # Escaped or unescaped — both are valid for the inferred grep.
    assert "mcp__code-graph__index_status" in r.command or \
           "mcp__code\\-graph__index_status" in r.command


def test_phase1_reproducer_infers_for_p1_baseDir():
    _, _, infer = _load_oracle()
    r = infer("P1", "example", "unresolved template placeholder '{baseDir}' in SKILL.md")
    assert r.type == "grep"
    assert "baseDir" in r.command


def test_phase1_reproducer_falls_back_to_manual():
    """Unknown code or evidence the inferrer can't reduce →
    type=manual. This is honest — better to flag for human review
    than to manufacture a predicate that might mislead."""
    _, _, infer = _load_oracle()
    r = infer("Z9", "example", "totally unrecognized finding shape")
    assert r.type == "manual"


def test_discover_phase1_only_against_real_tree():
    """Smoke test: discover_phase1_only against the audit-skill
    self-audit produces well-formed Finding objects with
    Reproducers (mostly manual, since most current Phase 1 findings
    are clean against the live tree — this verifies the discovery
    path itself works)."""
    phase1, _, _ = _load_oracle()
    findings = phase1(REPO, skill="audit-skill")
    # Either zero findings (clean) or some — both are valid; this
    # test just confirms the call doesn't crash.
    assert isinstance(findings, list)
    for f in findings:
        assert f.skill == "audit-skill"
        assert f.code  # non-empty
        assert f.reproducer is not None


def test_discover_worklist_emits_act_on_report(tmp_path, monkeypatch):
    """discover_worklist returns an ActOnReport with the same fields
    the orchestrator expects from act_on. End-to-end: lint runs,
    reverify runs, worklist comes out filtered."""
    phase1, discover, _ = _load_oracle()
    monkeypatch.setenv("AUDIT_SKILL_ORACLE_TRACE", str(tmp_path / "trace.jsonl"))
    report = discover(REPO, skill="audit-skill")
    # ActOnReport has these fields
    assert hasattr(report, "worklist")
    assert hasattr(report, "stale")
    assert hasattr(report, "still_fires")
    assert hasattr(report, "manual")
    assert hasattr(report, "error")
    assert isinstance(report.stale_rate, float)
