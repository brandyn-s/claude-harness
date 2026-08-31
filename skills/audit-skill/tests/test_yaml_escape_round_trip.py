"""Tests for the YAML escape round-trip (root cause of 2026-05-26 corruption).

INCIDENT 2026-05-26: descriptions in AUDIT-TRACKERS/05-phase2-findings.findings.yaml
accumulated runs of literal backslashes (up to 126 per finding) across
multiple set-triage-status calls. Root cause:
  - oracle.tracker._yaml_escape encodes `\\` → `\\\\` and `"` → `\\"`
  - oracle.finding._parse_minimal_yaml stripped quotes WITHOUT decoding
    the escape sequences
Every load → modify → write pass doubled the backslash count.

The fix: the parser now decodes `\\\\` → `\\` and `\\"` → `"` in
double-quoted strings (via _decode_double_quoted). These tests pin the
round-trip stability so a future "minimal parser" tweak doesn't
regress.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "skills" / "_shared"))

from oracle.finding import _decode_double_quoted, _parse_minimal_yaml  # noqa: E402
from oracle.tracker import _yaml_escape  # noqa: E402


def test_decode_double_quoted_escapes():
    """The decoder reverses what _yaml_escape produces."""
    assert _decode_double_quoted('\\"') == '"'
    assert _decode_double_quoted('\\\\') == '\\'
    assert _decode_double_quoted('\\n') == '\n'
    assert _decode_double_quoted('\\t') == '\t'
    assert _decode_double_quoted('\\r') == '\r'


def test_decode_preserves_unknown_escapes():
    """Don't lose data on novel escape sequences."""
    assert _decode_double_quoted('\\x') == '\\x'
    assert _decode_double_quoted('\\$') == '\\$'


def test_decode_handles_plain_text():
    """No escapes — return as-is."""
    assert _decode_double_quoted("no escapes") == "no escapes"
    assert _decode_double_quoted("") == ""


def test_decode_handles_trailing_backslash():
    """Don't crash on a trailing backslash (encoder shouldn't produce
    this, but be defensive)."""
    assert _decode_double_quoted("foo\\") == "foo\\"


def _round_trip(s: str) -> str:
    """Encode + parse a single description, return what came back."""
    encoded = _yaml_escape(s)
    fake_yaml = (
        f"findings:\n"
        f"  - skill: foo\n"
        f"    code: A1\n"
        f"    severity: drift\n"
        f"    label: behavior-fix\n"
        f"    description: {encoded}\n"
        f"    reproducer:\n"
        f"      type: manual\n"
    )
    parsed = _parse_minimal_yaml(fake_yaml)
    return parsed["findings"][0]["description"]


def test_round_trip_simple_text():
    assert _round_trip("plain text") == "plain text"


def test_round_trip_text_with_quote():
    """The bug-trigger case from the May 2026 ship-hook A3 finding."""
    s = 'Line 126 claims "Python atomic read-modify-write" - NOT atomic'
    assert _round_trip(s) == s


def test_round_trip_text_with_backslash():
    s = "Windows path: C:\\Users\\foo"
    assert _round_trip(s) == s


def test_round_trip_text_with_both_quote_and_backslash():
    s = 'Mixed: "quoted" plus \\backslash\\'
    assert _round_trip(s) == s


def test_round_trip_idempotent_after_5_passes():
    """Multiple load → write cycles must not drift. This is the
    invariant the original corruption violated (each pass doubled
    backslashes before quotes)."""
    s_original = 'Line claims "X is atomic" - but actually it is NOT atomic'
    s = s_original
    for pass_n in range(5):
        s_next = _round_trip(s)
        assert s_next == s_original, (
            f"DRIFT at pass {pass_n}: expected {s_original!r}, got {s_next!r}"
        )
        s = s_next


def test_round_trip_block_scalar_unchanged():
    """The block-scalar code path (|) is unaffected by escape decoding."""
    block_yaml = """findings:
  - skill: foo
    code: A1
    severity: drift
    label: behavior-fix
    description: |
      line one with "quote"
      line two with \\backslash
    reproducer:
      type: manual
"""
    parsed = _parse_minimal_yaml(block_yaml)
    desc = parsed["findings"][0]["description"]
    # Block scalars are taken literally — no escape decoding.
    assert '"quote"' in desc
    assert "\\backslash" in desc


# ---------------------------------------------------------------------------
# 2026-06-12 campaign-11 instrument fixes: folded flow scalars, garbage
# input, empty findings, and multi-line command round-trip through the
# act-on worklist writer. Each test pins one of the four loader/writer
# bugs found while the audit verified its own harness.
# ---------------------------------------------------------------------------

def test_folded_flow_scalar_continuation_preserved():
    """PyYAML width-folding continues a flow scalar on the next (more
    indented) line; the parser must unfold it to a single space instead
    of silently truncating. 2026-06-12: 68/68 folded commands loaded
    truncated (trailing ' ]' dropped -> bash rc=2 -> false STALE)."""
    folded = """findings:
  - skill: x
    code: B
    severity: info
    label: doc-fix
    description: d
    reproducer:
      type: bash
      command: echo aaaa && [ -n "x"
        ]
"""
    parsed = _parse_minimal_yaml(folded)
    cmd = parsed["findings"][0]["reproducer"]["command"]
    assert cmd == 'echo aaaa && [ -n "x" ]'


def test_folded_quoted_scalar_closing_quote_on_continuation():
    """A folded SINGLE-QUOTED scalar may carry its closing quote on the
    continuation line; quote-stripping must happen after re-attachment."""
    folded = """findings:
  - skill: x
    code: B
    severity: info
    label: doc-fix
    description: 'first part
      second part'
    reproducer:
      type: manual
"""
    parsed = _parse_minimal_yaml(folded)
    assert parsed["findings"][0]["description"] == "first part second part"


def test_garbage_input_raises_instead_of_empty_success(tmp_path):
    """Garbage input (PyYAML-rejected) must raise FindingsParseError —
    silently returning zero findings let a corrupted tracker sail through
    reverify/act-on as 'nothing to fix' (2026-06-12 finding). A VALID
    document that merely lacks findings stays OK (see
    test_load_findings_missing_findings_key_is_OK in test_oracle_validate)."""
    from oracle.finding import FindingsParseError, load_findings

    bad = tmp_path / "bad.yaml"
    bad.write_text("not: valid: yaml: [unclosed\n", encoding="utf-8")
    with pytest.raises(FindingsParseError):
        load_findings(bad)


def test_flow_style_empty_findings_accepted():
    """`findings: []` is a legitimate empty worklist, not garbage."""
    parsed = _parse_minimal_yaml("findings: []\n")
    assert parsed["findings"] == []


def test_to_yaml_multiline_command_round_trips():
    """tracker._to_yaml must emit multi-line commands as block scalars;
    the old newline->space flattening turned python reproducers into
    one-line SyntaxErrors on every act-on worklist round-trip."""
    from oracle.finding import Finding, Reproducer
    from oracle.tracker import _to_yaml

    snippet = "import sys\nsys.exit(1)"
    f = Finding(
        skill="fixture", code="T9", severity="info", label="behavior-fix",
        description="multi-line python reproducer",
        reproducer=Reproducer(type="python", command=snippet),
    )
    emitted = _to_yaml([f])
    parsed = _parse_minimal_yaml(emitted)
    assert parsed["findings"][0]["reproducer"]["command"] == snippet


def test_to_yaml_round_trips_extra_fields():
    """Unknown finding fields route into Finding.extra on load and MUST be
    written back by _to_yaml — the first set-triage-status rewrite of the
    campaign-11 tracker silently dropped all 451 location: fields
    (2026-06-12 finding)."""
    from oracle.finding import Finding, Reproducer
    from oracle.tracker import _to_yaml

    f = Finding(
        skill="fixture", code="B", severity="info", label="doc-fix",
        description="extras must survive rewrites",
        reproducer=Reproducer(type="manual"),
        extra={"location": "skills/fixture/SKILL.md:7",
               "oracle_verdict": "STILL-FIRES"},
    )
    emitted = _to_yaml([f])
    parsed = _parse_minimal_yaml(emitted)
    row = parsed["findings"][0]
    assert row["location"] == "skills/fixture/SKILL.md:7"
    assert row["oracle_verdict"] == "STILL-FIRES"
