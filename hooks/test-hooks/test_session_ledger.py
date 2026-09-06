#!/usr/bin/env python3
"""Tests for hooks/session_ledger.py -- the acceptance ledger's own contracts.

Offline, in-process. What is pinned here:
  - render_for_injection is FRAME FIRST: rejected, then what done means, then how
  - entries ingested from INTENT.md are labelled as the task frame
  - add_entry de-duplicates and never drops a REJECTED entry to make room
  - audit_against_summary is token containment (paraphrase survives, a dropped
    rejection does not) and audit_row / append_audit_row record it as JSONL
  - a session id is filesystem-safe before it becomes a path
"""
import importlib.util
import json
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("session_ledger_under_test", HOOKS / "session_ledger.py")
sl = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sl
_spec.loader.exec_module(sl)


def _ledger():
    ledger = sl.new_ledger("sess-1", "/work/x")
    sl.add_entry(ledger, sl.DELIVERABLE, "Produce the handoff document", source="INTENT.md")
    sl.add_entry(ledger, sl.CONSTRAINT, "No changes outside hooks/")
    sl.add_entry(ledger, sl.REJECTED, "Do not add a Stop hook phrase blocker")
    sl.add_entry(ledger, sl.EVIDENCE, "Show the test output, not a claim")
    sl.add_entry(ledger, sl.OPEN_QUESTION, "Which profile ships the operator layer")
    return ledger


def test_render_is_frame_first_rejected_then_deliverables_then_constraints():
    text = sl.render_for_injection(_ledger())
    i_rej = text.index("EXPLICITLY REJECTED")
    i_del = text.index("REQUIRED DELIVERABLES")
    i_con = text.index("CONSTRAINTS")
    i_evi = text.index("EVIDENCE STANDARD")
    assert i_rej < i_del < i_con < i_evi
    assert sl.INJECTION_ORDER[:3] == (sl.REJECTED, sl.DELIVERABLE, sl.CONSTRAINT)


def test_render_labels_frame_sourced_entries():
    text = sl.render_for_injection(_ledger())
    assert "- Produce the handoff document [INTENT.md]" in text
    assert "- No changes outside hooks/" in text and "No changes outside hooks/ [" not in text
    assert "come from the task frame (1)" in text


def test_render_empty_ledger_is_empty_string():
    assert sl.render_for_injection(sl.new_ledger("s")) == ""
    assert sl.render_for_injection({}) == ""


def test_add_entry_dedupes_and_counts_restatements():
    ledger = sl.new_ledger("s")
    sl.add_entry(ledger, sl.CONSTRAINT, "Keep it   under 3 KB")
    sl.add_entry(ledger, sl.CONSTRAINT, "keep it under 3 kb")
    assert len(ledger["entries"]) == 1
    assert ledger["entries"][0]["restated"] == 1
    assert "(restated 1x)" in sl.render_for_injection(ledger)


def test_cap_never_drops_a_rejected_entry():
    ledger = sl.new_ledger("s")
    sl.add_entry(ledger, sl.REJECTED, "never do the thing")
    for i in range(sl.MAX_ENTRIES + 20):
        sl.add_entry(ledger, sl.DECISION, f"decision number {i}")
    kinds = [e["kind"] for e in ledger["entries"]]
    assert sl.REJECTED in kinds
    assert len(ledger["entries"]) <= sl.MAX_ENTRIES


def test_audit_is_token_containment_not_substring():
    ledger = _ledger()
    covering = ("We must produce the handoff document, with no changes outside hooks/; show the test "
                "output and not a claim; the user rejected adding a Stop hook phrase blocker; still open: "
                "which profile ships the operator layer")
    audit = sl.audit_against_summary(ledger, covering)
    assert audit["not_found_in_summary"] == []
    assert audit["rejected_dropped"] == []
    dropped = sl.audit_against_summary(ledger, "We produced the handoff document and kept changes inside hooks/.")
    assert any(m["kind"] == sl.REJECTED for m in dropped["rejected_dropped"])


def test_audit_row_and_append(tmp_path):
    ledger = sl.mark_compaction(_ledger())
    row = sl.audit_row(ledger, "handoff document produced", trigger="auto", now=1_757_000_000.0)
    assert row["session_id"] == "sess-1" and row["trigger"] == "auto" and row["compaction_count"] == 1
    assert row["total_entries"] == 5
    assert row["rejected_dropped_count"] == 1
    assert row["date"] == "2025-09-04"
    assert all(set(m) == {"kind", "text"} for m in row["not_found"])
    path = sl.append_audit_row(row, audit_dir=tmp_path)
    assert path is not None and path.name == "ledger-audit-20250904.jsonl"
    sl.append_audit_row(row, audit_dir=tmp_path)
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and rows[0]["rejected_dropped_count"] == 1


def test_append_audit_row_never_raises(tmp_path):
    blocked = tmp_path / "file-not-dir"
    blocked.write_text("x", encoding="utf-8")
    assert sl.append_audit_row({"ts": 0}, audit_dir=blocked) is None


def test_session_id_is_filesystem_safe():
    assert sl._safe_session_id("../../etc/passwd") == "etcpasswd"
    assert sl.ledger_path("a/b", Path("/tmp/x")).name == "ab.json"
    assert sl._safe_session_id("") == "unknown"


def test_save_and_load_roundtrip(tmp_path):
    ledger = _ledger()
    assert sl.save(ledger, ledger_dir=tmp_path)
    back = sl.load("sess-1", ledger_dir=tmp_path)
    assert back is not None and len(back["entries"]) == 5
    (tmp_path / "sess-1.json").write_text("{not json", encoding="utf-8")
    assert sl.load("sess-1", ledger_dir=tmp_path) is None      # corrupt degrades to absent
