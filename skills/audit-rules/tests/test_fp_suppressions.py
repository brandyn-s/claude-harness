"""Tests for the durable FP suppression workflow (Phase 5).

The scanner reads AUDIT-TRACKERS/rule-suppressions.yaml on every run
and filters matching violations BEFORE they aggregate into the rate.
This pins the filtering semantics so a future scanner edit doesn't
silently regress suppression.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
SCANNER = REPO / "skills" / "audit-rules" / "references" / "scan_violations.py"


def _load_scanner():
    """Import scan_violations.py as a module."""
    spec = importlib.util.spec_from_file_location("scan_violations", SCANNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_tracker_records_violation_without_suppression():
    """No suppression entries → normal recording path."""
    sv = _load_scanner()
    t = sv.ViolationTracker()
    t.sessions_scanned = 1
    t.record("encoding-missing-open", "session-abc", "open('foo.json')")
    assert t.counts["encoding-missing-open"] == 1
    assert t.suppressed_counts.get("encoding-missing-open", 0) == 0


def test_tracker_filters_by_pattern():
    """Pattern-matching suppression: any violation whose excerpt
    contains the pattern (case-insensitive) is excluded."""
    sv = _load_scanner()
    t = sv.ViolationTracker(suppressions=[
        {
            "rule": "encoding-missing-open",
            "pattern": "open('/tmp/audit",
            "reason": "audit fixtures intentionally use temp paths",
        }
    ])
    t.sessions_scanned = 1
    t.record("encoding-missing-open", "s1", "open('/tmp/audit/foo.json')")
    t.record("encoding-missing-open", "s2", "open('real-file.py')")
    assert t.counts["encoding-missing-open"] == 1, (
        "real violation must still count"
    )
    assert t.suppressed_counts["encoding-missing-open"] == 1, (
        "fixture violation must be suppressed-counted"
    )


def test_tracker_filters_by_session_id():
    """Session-specific suppression: this one session is exempted."""
    sv = _load_scanner()
    t = sv.ViolationTracker(suppressions=[
        {
            "rule": "websearch-webfetch-used",
            "session_id": "063049f8-bf1",
            "reason": "operator authorized for research session",
        }
    ])
    t.sessions_scanned = 1
    t.record("websearch-webfetch-used", "063049f8-bf1-9999", "WebSearch")
    t.record("websearch-webfetch-used", "abcdef12-3456", "WebSearch")
    assert t.counts["websearch-webfetch-used"] == 1
    assert t.suppressed_counts["websearch-webfetch-used"] == 1


def test_tracker_pattern_is_case_insensitive():
    """Real-world data has mixed casing; suppression must match."""
    sv = _load_scanner()
    t = sv.ViolationTracker(suppressions=[
        {"rule": "r", "pattern": "binary_mode", "reason": "..."}
    ])
    t.sessions_scanned = 1
    t.record("r", "s1", "BINARY_MODE = 'rb'")
    assert t.suppressed_counts["r"] == 1


def test_tracker_only_suppresses_matching_rule():
    """A suppression for rule X must NOT suppress rule Y."""
    sv = _load_scanner()
    t = sv.ViolationTracker(suppressions=[
        {"rule": "rule_x", "pattern": "foo", "reason": "..."}
    ])
    t.sessions_scanned = 1
    t.record("rule_x", "s1", "foo()")  # suppressed
    t.record("rule_y", "s2", "foo()")  # NOT suppressed
    assert t.suppressed_counts["rule_x"] == 1
    assert t.counts["rule_y"] == 1
    assert t.suppressed_counts.get("rule_y", 0) == 0


def test_tracker_expired_suppression_is_inactive(monkeypatch):
    """A suppression past its expires date no longer fires."""
    sv = _load_scanner()
    t = sv.ViolationTracker(suppressions=[
        {
            "rule": "r",
            "pattern": "foo",
            "reason": "expired",
            "expires": "2020-01-01",  # past
        }
    ])
    t.sessions_scanned = 1
    t.record("r", "s1", "foo()")
    assert t.counts["r"] == 1
    assert t.suppressed_counts.get("r", 0) == 0


def test_tracker_unexpired_suppression_fires():
    """A suppression before its expires date still fires."""
    sv = _load_scanner()
    t = sv.ViolationTracker(suppressions=[
        {
            "rule": "r",
            "pattern": "foo",
            "reason": "ok",
            "expires": "2099-12-31",  # future
        }
    ])
    t.sessions_scanned = 1
    t.record("r", "s1", "foo()")
    assert t.suppressed_counts["r"] == 1


def test_load_suppressions_returns_empty_when_file_missing(tmp_path):
    """Missing file → empty list (no crash)."""
    sv = _load_scanner()
    suppressions = sv._load_suppressions(tmp_path)
    assert suppressions == []


def test_load_suppressions_parses_valid_entries(tmp_path):
    """Loader correctly parses well-formed YAML."""
    sv = _load_scanner()
    (tmp_path / "AUDIT-TRACKERS").mkdir()
    (tmp_path / "AUDIT-TRACKERS" / "rule-suppressions.yaml").write_text(
        "suppressions:\n"
        "  - rule: encoding-missing-open\n"
        "    pattern: foo\n"
        "    reason: test\n"
        "  - rule: websearch-webfetch-used\n"
        "    session_id: abc123\n"
        "    reason: test session\n",
        encoding="utf-8",
    )
    suppressions = sv._load_suppressions(tmp_path)
    assert len(suppressions) == 2
    assert suppressions[0]["rule"] == "encoding-missing-open"
    assert suppressions[0]["pattern"] == "foo"
    assert suppressions[1]["session_id"] == "abc123"


def test_load_suppressions_drops_malformed_entries(tmp_path):
    """Entries missing required fields are dropped, not crashed on."""
    sv = _load_scanner()
    (tmp_path / "AUDIT-TRACKERS").mkdir()
    (tmp_path / "AUDIT-TRACKERS" / "rule-suppressions.yaml").write_text(
        "suppressions:\n"
        "  - rule: missing-reason\n"
        "    pattern: foo\n"
        # no reason
        "  - rule: missing-matcher\n"
        "    reason: ok\n"
        # no pattern or session_id
        "  - rule: valid-entry\n"
        "    pattern: bar\n"
        "    reason: ok\n",
        encoding="utf-8",
    )
    suppressions = sv._load_suppressions(tmp_path)
    assert len(suppressions) == 1
    assert suppressions[0]["rule"] == "valid-entry"


def test_to_dict_surfaces_suppressed_counts():
    """The JSON output must expose suppressed_count per rule + a
    top-level suppressed dict. Operators need both to audit suppression."""
    sv = _load_scanner()
    t = sv.ViolationTracker(suppressions=[
        {"rule": "r", "pattern": "foo", "reason": "ok"}
    ])
    t.sessions_scanned = 5
    t.record("r", "s1", "foo()")
    t.record("r", "s2", "bar()")  # not suppressed
    out = t.to_dict()
    assert out["suppressed"] == {"r": 1}
    assert out["violations"]["r"]["suppressed_count"] == 1
    assert out["violations"]["r"]["count"] == 1
