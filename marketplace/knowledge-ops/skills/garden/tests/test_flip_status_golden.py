"""Golden tests for garden/scripts/flip_status.py — the open-STATUS-marker
auto-flip / auto-date mutator.

This is the B8c F8 fixture (AUDIT-TRACKERS/02-golden-tests.md): the flip
"mechanically mutates KB pages; highest blast radius of any untested
procedure in the family". Until 2026-06-11 the flip lived as prose-only
instructions in SKILL.md ("flip the marker in place to `> **STATUS:**
RESOLVED <date> — see <entry>`") executed by hand-editing; these tests pin
the extracted script's contract:

  (a) OPEN marker + resolution evidence → flipped in place with date;
      every other byte of the file is identical
  (b) OPEN marker, no resolution given (report mode) → file untouched
  (c) undated OPEN marker (bare and `(since ?)`) → auto-dated
  (d) idempotency — a second identical run changes nothing
  (e) file with no markers → exit 0, no change
  plus: ambiguity guard (two eligible markers without --match → exit 2,
  untouched), --match targeting, attribution comment, newline
  preservation, and detection agreement with analyze.py's marker regexes.

All invocations go through a real subprocess against tmp_path fixtures.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SCRIPT = SCRIPTS / "flip_status.py"

_SPEC = importlib.util.spec_from_file_location("garden_analyze", SCRIPTS / "analyze.py")
analyze_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(analyze_mod)


def run(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *[str(a) for a in args]],
        capture_output=True, text=True)


OPEN_LINE = ("> **STATUS:** OPEN (since 2026-06-06) — Athena messages empty; "
             "bulk chat-content scans unavailable until the worker fix deploys.")

TOPIC = f"""---
title: Audit Pipeline Gaps
description: Test topic for the STATUS-marker mutator.
stage: seedling
tags: [audit, testing]
created: 2026-06-01
updated: 2026-06-07
---
# Audit Pipeline Gaps

> One-line human description.

---

## Athena messages empty (2026-06-06)

{OPEN_LINE}

Body prose that must survive byte-identical, including `code spans`
and [[wiki-links|Wiki Links]].

## Projection fix shipped (2026-06-07)

The #382 projection fix landed with the Apr/May backfills.
"""


def write_topic(tmp_path, content=TOPIC, name="audit-pipeline-gaps.md"):
    p = tmp_path / name
    # write_bytes, not write_text: text mode translates \n -> os.linesep on
    # Windows, giving CRLF fixtures that flip_status then (correctly)
    # preserves — failing the byte-level line assertions on windows-2022
    # while passing everywhere else (PR #1162 matrix run, 2026-06-11).
    # Fixtures are deterministic LF on every platform; CRLF preservation
    # has its own explicit test below.
    p.write_bytes(content.encode("utf-8"))
    return p


# ── (a) flip with resolution evidence ────────────────────────────────────────

def test_flip_resolved_in_place_rest_byte_identical(tmp_path):
    p = write_topic(tmp_path)
    before_lines = p.read_bytes().split(b"\n")

    r = run(p, "--resolved", "2026-06-07", "--details", "entry below / PR #382")
    assert r.returncode == 0, r.stderr

    after_lines = p.read_bytes().split(b"\n")
    assert len(after_lines) == len(before_lines)  # line-scoped: no insertions
    diffs = [i for i, (b, a) in enumerate(zip(before_lines, after_lines)) if b != a]
    assert len(diffs) == 1  # exactly one line changed
    flipped = after_lines[diffs[0]].decode("utf-8")
    assert flipped == (
        "> **STATUS:** RESOLVED 2026-06-07 — Athena messages empty; "
        "bulk chat-content scans unavailable until the worker fix deploys. "
        "[details: entry below / PR #382]")


def test_flip_summary_replaces_description(tmp_path):
    p = write_topic(tmp_path)
    r = run(p, "--resolved", "2026-06-07", "--details", "PR #382",
            "--summary", "see entry below")
    assert r.returncode == 0, r.stderr
    text = p.read_text(encoding="utf-8")
    assert ("> **STATUS:** RESOLVED 2026-06-07 — see entry below "
            "[details: PR #382]") in text
    assert "OPEN" not in text.split("STATUS:** ")[1].split("\n")[0]


def test_flip_requires_details(tmp_path):
    p = write_topic(tmp_path)
    before = p.read_bytes()
    r = run(p, "--resolved", "2026-06-07")
    assert r.returncode == 2  # argparse usage error
    assert p.read_bytes() == before


# ── (b) no resolution given → untouched ──────────────────────────────────────

def test_report_mode_never_writes(tmp_path):
    p = write_topic(tmp_path)
    before = p.read_bytes()
    r = run(p)
    assert r.returncode == 0, r.stderr
    assert p.read_bytes() == before
    assert "since 2026-06-06" in r.stdout


# ── (c) undated OPEN → auto-dated ────────────────────────────────────────────

def test_auto_date_bare_marker(tmp_path):
    body = TOPIC.replace(
        OPEN_LINE, "> **STATUS:** OPEN — bulk scans unavailable")
    p = write_topic(tmp_path, body)
    before_lines = p.read_bytes().split(b"\n")

    r = run(p, "--auto-date", "2026-06-06")
    assert r.returncode == 0, r.stderr

    after_lines = p.read_bytes().split(b"\n")
    diffs = [i for i, (b, a) in enumerate(zip(before_lines, after_lines)) if b != a]
    assert len(after_lines) == len(before_lines) and len(diffs) == 1
    assert after_lines[diffs[0]].decode("utf-8") == (
        "> **STATUS:** OPEN (since 2026-06-06) — bulk scans unavailable")


def test_auto_date_since_question_mark_placeholder(tmp_path):
    body = TOPIC.replace(
        OPEN_LINE, "> **STATUS:** OPEN (since ?) — bulk scans unavailable")
    p = write_topic(tmp_path, body)
    r = run(p, "--auto-date", "2026-06-06")
    assert r.returncode == 0, r.stderr
    assert ("> **STATUS:** OPEN (since 2026-06-06) — bulk scans unavailable"
            in p.read_text(encoding="utf-8"))


def test_auto_date_skips_already_dated_marker(tmp_path):
    p = write_topic(tmp_path)  # marker already has (since 2026-06-06)
    before = p.read_bytes()
    r = run(p, "--auto-date", "2026-06-10")
    assert r.returncode == 0, r.stderr
    assert p.read_bytes() == before
    assert "nothing to do" in r.stdout


# ── (d) idempotency ──────────────────────────────────────────────────────────

def test_flip_is_idempotent(tmp_path):
    p = write_topic(tmp_path)
    args = (p, "--resolved", "2026-06-07", "--details", "entry below / PR #382")
    assert run(*args).returncode == 0
    after_first = p.read_bytes()
    r2 = run(*args)
    assert r2.returncode == 0, r2.stderr
    assert p.read_bytes() == after_first
    assert "nothing to do" in r2.stdout


def test_auto_date_is_idempotent(tmp_path):
    body = TOPIC.replace(
        OPEN_LINE, "> **STATUS:** OPEN — bulk scans unavailable")
    p = write_topic(tmp_path, body)
    args = (p, "--auto-date", "2026-06-06")
    assert run(*args).returncode == 0
    after_first = p.read_bytes()
    r2 = run(*args)
    assert r2.returncode == 0, r2.stderr
    assert p.read_bytes() == after_first


# ── (e) file with no markers ─────────────────────────────────────────────────

def test_no_markers_exit_zero_no_change(tmp_path):
    body = TOPIC.replace(OPEN_LINE, "Plain prose; no state-claim here.")
    p = write_topic(tmp_path, body)
    before = p.read_bytes()
    for args in ((p,),
                 (p, "--resolved", "2026-06-07", "--details", "PR #1"),
                 (p, "--auto-date", "2026-06-07")):
        r = run(*args)
        assert r.returncode == 0, r.stderr
        assert p.read_bytes() == before


# ── safety: ambiguity guard + targeting ──────────────────────────────────────

TWO_MARKERS = TOPIC.replace(
    "## Projection fix shipped (2026-06-07)",
    "## Second gap (2026-06-07)\n\n"
    "> **STATUS:** OPEN (since 2026-06-07) — Firehose lag alarms missing.\n\n"
    "## Projection fix shipped (2026-06-07)")


def test_two_eligible_markers_without_match_exit_2_untouched(tmp_path):
    p = write_topic(tmp_path, TWO_MARKERS)
    before = p.read_bytes()
    r = run(p, "--resolved", "2026-06-07", "--details", "PR #382")
    assert r.returncode == 2
    assert "more than one eligible" in r.stderr
    assert p.read_bytes() == before


def test_match_selects_exactly_one_marker(tmp_path):
    p = write_topic(tmp_path, TWO_MARKERS)
    r = run(p, "--resolved", "2026-06-07", "--details", "PR #382",
            "--match", "Firehose")
    assert r.returncode == 0, r.stderr
    text = p.read_text(encoding="utf-8")
    assert ("> **STATUS:** RESOLVED 2026-06-07 — Firehose lag alarms missing. "
            "[details: PR #382]") in text
    assert OPEN_LINE in text  # the OTHER marker is untouched


def test_match_nothing_is_noop_exit_zero(tmp_path):
    p = write_topic(tmp_path)
    before = p.read_bytes()
    r = run(p, "--resolved", "2026-06-07", "--details", "PR #1",
            "--match", "no-such-substring")
    assert r.returncode == 0, r.stderr
    assert p.read_bytes() == before


# ── attribution + encoding/newline preservation ──────────────────────────────

def test_garden_date_appends_attribution_comment(tmp_path):
    p = write_topic(tmp_path)
    r = run(p, "--resolved", "2026-06-07", "--details", "PR #382",
            "--garden-date", "2026-06-11")
    assert r.returncode == 0, r.stderr
    text = p.read_text(encoding="utf-8")
    assert ("[details: PR #382] "
            "<!-- garden: 2026-06-11 action:open-marker-flip -->") in text


def test_crlf_endings_preserved(tmp_path):
    p = tmp_path / "crlf.md"
    p.write_bytes(TOPIC.replace("\n", "\r\n").encode("utf-8"))
    r = run(p, "--resolved", "2026-06-07", "--details", "PR #382")
    assert r.returncode == 0, r.stderr
    raw = p.read_bytes()
    assert b"\r\n" in raw
    assert b"RESOLVED 2026-06-07" in raw
    # No bare-LF lines were introduced by the rewrite.
    assert raw.count(b"\n") == raw.count(b"\r\n")


def test_missing_file_exit_1(tmp_path):
    r = run(tmp_path / "absent.md", "--auto-date", "2026-06-07")
    assert r.returncode == 1


def test_calendar_invalid_date_rejected_exit_2_untouched(tmp_path):
    p = write_topic(tmp_path)
    before = p.read_bytes()
    r = run(p, "--resolved", "2026-13-99", "--details", "PR #382")
    assert r.returncode == 2  # argparse usage error
    assert "not a calendar-valid date" in r.stderr
    assert "Traceback" not in r.stderr
    assert p.read_bytes() == before


def test_non_utf8_file_clean_error_exit_1(tmp_path):
    p = tmp_path / "binary.md"
    p.write_bytes(b"\xff\xfe\x00")
    r = run(p)
    assert r.returncode == 1
    assert "ERROR: not UTF-8 text" in r.stderr
    assert "Traceback" not in r.stderr


def test_help_short_circuits(tmp_path):
    r = run("--help")
    assert r.returncode == 0
    assert "--resolved" in r.stdout and "--auto-date" in r.stdout


# ── detection agreement with analyze.py ──────────────────────────────────────

def test_flipped_marker_leaves_analyzer_open_inventory(tmp_path):
    p = write_topic(tmp_path)
    assert len(analyze_mod.analyze(str(tmp_path))["open_markers"]) == 1
    run(p, "--resolved", "2026-06-07", "--details", "PR #382")
    report = analyze_mod.analyze(str(tmp_path))
    assert report["open_markers"] == []
    assert report["undated_open_markers"] == []


def test_auto_dated_marker_moves_to_dated_open_inventory(tmp_path):
    body = TOPIC.replace(
        OPEN_LINE, "> **STATUS:** OPEN — bulk scans unavailable")
    p = write_topic(tmp_path, body)
    assert len(analyze_mod.analyze(str(tmp_path))["undated_open_markers"]) == 1
    run(p, "--auto-date", "2026-06-06")
    report = analyze_mod.analyze(str(tmp_path))
    assert report["undated_open_markers"] == []
    assert [m["since"] for m in report["open_markers"]] == ["2026-06-06"]
