"""Tests for the block-then-fix awareness added 2026-06-16 (C+B).

For hook-enforced rules, scan_violations.py splits the attempted
session_rate_pct into block-then-fix (the guard fired; the scanner counted
the pre-block attempt) vs net-silent (the violation actually executed). The
split is computed from RULE_BLOCK_SIGNATURES + per-session block-signature
presence. These tests pin:
  - session_rate_pct is UNCHANGED (lifecycle_check + scan_to_findings read it)
  - the breakdown fields are correct and only present for mapped rules
  - note_block_signatures records the intersecting sessions
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCANNER = REPO / "skills" / "audit-rules" / "references" / "scan_violations.py"


def _load_scanner():
    spec = importlib.util.spec_from_file_location("scan_violations", SCANNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_block_signature_map_includes_encoding_rule():
    """Regression guard: the encoding rule must stay mapped with its
    verified guard signatures (2026-06-16 forensics)."""
    sv = _load_scanner()
    assert "encoding-missing-open" in sv.RULE_BLOCK_SIGNATURES
    sigs = sv.RULE_BLOCK_SIGNATURES["encoding-missing-open"]
    assert "[inline-encoding-guard]" in sigs
    assert "without encoding='utf-8' at" in sigs


def test_note_block_signatures_records_when_signature_present():
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.note_block_signatures("s1", "tool error: [inline-encoding-guard] BLOCKED: ...")
    assert "s1" in t.sessions_with_block_sig["encoding-missing-open"]


def test_note_block_signatures_ignores_unrelated_line():
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.note_block_signatures("s1", "just a normal assistant message about open files")
    assert "s1" not in t.sessions_with_block_sig["encoding-missing-open"]


def test_note_block_signatures_idempotent():
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.note_block_signatures("s1", "[heredoc-encoding-guard] BLOCKED")
    t.note_block_signatures("s1", "[heredoc-encoding-guard] BLOCKED")
    assert t.sessions_with_block_sig["encoding-missing-open"] == {"s1"}


def test_to_dict_splits_block_then_fix_vs_net_silent():
    """Session with a block signature → block-then-fix; without → net-silent."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 10
    # session A: violation + block signature → the hook fired (block-then-fix)
    t.record("encoding-missing-open", "sessA", "open('a.json')")
    t.note_block_signatures("sessA", "[inline-encoding-guard] BLOCKED: ...")
    # session B: violation, no block signature → executed unblocked (net-silent)
    t.record("encoding-missing-open", "sessB", "open('b.json')")
    out = t.to_dict()["violations"]["encoding-missing-open"]
    assert out["unique_sessions"] == 2
    assert out["session_rate_pct"] == 20.0  # attempted rate, contract preserved
    assert out["blocked_then_fixed_sessions"] == 1
    assert out["net_silent_sessions"] == 1
    assert out["net_silent_rate_pct"] == 10.0  # 1 of 10 sessions


def test_session_rate_pct_preserved_for_mapped_rule():
    """Explicit consumer-contract guard: lifecycle_check + scan_to_findings
    read session_rate_pct; the additive change must not alter it."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 4
    t.record("encoding-missing-open", "s1", "open('x.json')")
    out = t.to_dict()["violations"]["encoding-missing-open"]
    assert out["session_rate_pct"] == 25.0


def test_unmapped_rule_has_no_breakdown_fields():
    """A rule absent from RULE_BLOCK_SIGNATURES reports the raw attempted
    rate exactly as before, with no net-silent fields."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 5
    t.record("git-commit-no-branch-check", "s1", "git commit -m x")
    out = t.to_dict()["violations"]["git-commit-no-branch-check"]
    assert out["session_rate_pct"] == 20.0
    assert "net_silent_rate_pct" not in out
    assert "blocked_then_fixed_sessions" not in out


def test_block_sig_in_session_without_violation_does_not_create_entry():
    """A block signature in a session with no recorded violation must not
    fabricate a violation entry (block-sig tracking is independent of counts)."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 3
    t.note_block_signatures("s1", "[inline-encoding-guard] BLOCKED")
    out = t.to_dict()
    assert "encoding-missing-open" not in out["violations"]
