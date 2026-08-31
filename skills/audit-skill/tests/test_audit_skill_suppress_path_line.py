"""Unit tests for path/line discriminators in audit-suppress.yaml (PR-F).

Covers:
  - Schema validation: `line:` without `path:` is rejected.
  - Schema validation: malformed `line:` (non-numeric, bad range).
  - Matching: literal path, glob path, single line, line range.
  - End-to-end: `_apply_path_line_suppressions` filters findings.
"""

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
AUDIT_SCRIPT = REPO / "bin" / "audit-skill.py"


def _load_audit_module():
    if "audit_skill" in sys.modules:
        return sys.modules["audit_skill"]
    spec = importlib.util.spec_from_file_location("audit_skill", AUDIT_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules["audit_skill"] = mod
    return mod


# ───────── schema validation ─────────

def test_suppression_line_without_path_is_rejected(tmp_path):
    audit = _load_audit_module()
    sk = tmp_path / "fake"
    sk.mkdir()
    (sk / "audit-suppress.yaml").write_text(
        "suppressions:\n"
        "  - code: C5\n"
        "    line: 42\n"
        "    reason: testing\n",
        encoding="utf-8",
    )
    errors = []
    out = audit._load_suppressions(sk, on_invalid=lambda ln, m: errors.append((ln, m)))
    assert out == []  # rejected
    # Error message includes "`line:`" and "`path:`" tokens. Don't pin
    # the exact phrasing (em-dash vs hyphen, etc.) — match on tokens.
    assert any("`line:`" in m and "`path:`" in m for _ln, m in errors), \
        f"expected schema error mentioning line+path, got {errors}"


def test_suppression_malformed_line_int_is_rejected(tmp_path):
    audit = _load_audit_module()
    sk = tmp_path / "fake"
    sk.mkdir()
    (sk / "audit-suppress.yaml").write_text(
        "suppressions:\n"
        "  - code: C5\n"
        "    path: foo.py\n"
        "    line: not-a-number\n"
        "    reason: testing\n",
        encoding="utf-8",
    )
    errors = []
    out = audit._load_suppressions(sk, on_invalid=lambda ln, m: errors.append((ln, m)))
    assert out == []
    assert errors, f"expected schema error, got {errors}"


def test_suppression_malformed_line_range_is_rejected(tmp_path):
    audit = _load_audit_module()
    sk = tmp_path / "fake"
    sk.mkdir()
    (sk / "audit-suppress.yaml").write_text(
        "suppressions:\n"
        "  - code: C5\n"
        "    path: foo.py\n"
        "    line: 10-twenty\n"
        "    reason: testing\n",
        encoding="utf-8",
    )
    errors = []
    out = audit._load_suppressions(sk, on_invalid=lambda ln, m: errors.append((ln, m)))
    assert out == []
    assert errors, f"expected schema error, got {errors}"


def test_suppression_valid_single_line_parses(tmp_path):
    audit = _load_audit_module()
    sk = tmp_path / "fake"
    sk.mkdir()
    (sk / "audit-suppress.yaml").write_text(
        "suppressions:\n"
        "  - code: C5\n"
        "    path: scripts/x.py\n"
        "    line: 42\n"
        "    reason: testing\n",
        encoding="utf-8",
    )
    out = audit._load_suppressions(sk, on_invalid=lambda ln, m: None)
    assert len(out) == 1
    assert out[0]["line"] == "42"
    assert out[0]["path"] == "scripts/x.py"


def test_suppression_valid_line_range_parses(tmp_path):
    audit = _load_audit_module()
    sk = tmp_path / "fake"
    sk.mkdir()
    (sk / "audit-suppress.yaml").write_text(
        "suppressions:\n"
        "  - code: C5\n"
        "    path: scripts/x.py\n"
        "    line: 40-45\n"
        "    reason: testing\n",
        encoding="utf-8",
    )
    out = audit._load_suppressions(sk, on_invalid=lambda ln, m: None)
    assert len(out) == 1
    assert out[0]["line"] == "40-45"


# ───────── matching logic ─────────

def test_suppressed_path_literal_match():
    audit = _load_audit_module()
    s = [{"code": "C5", "path": "scripts/run.py", "reason": "x"}]
    assert audit._suppressed(s, "C5", path="scripts/run.py")
    assert not audit._suppressed(s, "C5", path="scripts/other.py")


def test_suppressed_path_glob_match():
    audit = _load_audit_module()
    s = [{"code": "C5", "path": "scripts/*.py", "reason": "x"}]
    assert audit._suppressed(s, "C5", path="scripts/run.py")
    assert audit._suppressed(s, "C5", path="scripts/other.py")
    assert not audit._suppressed(s, "C5", path="bin/run.py")


def test_suppressed_path_normalizes_windows_slashes():
    audit = _load_audit_module()
    s = [{"code": "C5", "path": "scripts/run.py", "reason": "x"}]
    # Even if the finding's path has backslashes (Windows), the suppression
    # path glob (which uses forward slashes per convention) should still match.
    assert audit._suppressed(s, "C5", path=r"scripts\run.py")


def test_suppressed_line_single_match():
    audit = _load_audit_module()
    s = [{"code": "C5", "path": "x.py", "line": "42", "reason": "x"}]
    assert audit._suppressed(s, "C5", path="x.py", line=42)
    assert not audit._suppressed(s, "C5", path="x.py", line=41)


def test_suppressed_line_range_match():
    audit = _load_audit_module()
    s = [{"code": "C5", "path": "x.py", "line": "40-45", "reason": "x"}]
    assert audit._suppressed(s, "C5", path="x.py", line=40)  # inclusive lo
    assert audit._suppressed(s, "C5", path="x.py", line=45)  # inclusive hi
    assert audit._suppressed(s, "C5", path="x.py", line=42)  # middle
    assert not audit._suppressed(s, "C5", path="x.py", line=39)
    assert not audit._suppressed(s, "C5", path="x.py", line=46)


def test_suppressed_path_required_when_line_set():
    """If finding doesn't supply a path, a path-keyed suppression should
    NOT match — otherwise we'd suppress findings from the wrong file."""
    audit = _load_audit_module()
    s = [{"code": "C5", "path": "x.py", "line": "42", "reason": "x"}]
    assert not audit._suppressed(s, "C5", line=42)  # no path → no match
    assert not audit._suppressed(s, "C5", path=None, line=42)


def test_apply_path_line_skips_target_only_suppressions():
    """A suppression with only `target:` (no path/line) is not in this
    layer's scope — it's handled at emission time. The post-filter
    shouldn't double-apply or accidentally expand coverage."""
    audit = _load_audit_module()
    Finding = audit.Finding
    findings = [
        Finding("M2", "info", "x", path="manifest.yaml", line=10),
        Finding("C5", "info", "y", path="scripts/run.py", line=42),
    ]
    suppressions = [
        {"code": "M2", "target": "tool", "reason": "x"},  # no path/line
    ]
    out = audit._apply_path_line_suppressions(findings, suppressions)
    assert out == findings  # unchanged


def test_apply_path_line_filters_by_path():
    audit = _load_audit_module()
    Finding = audit.Finding
    findings = [
        Finding("C5", "info", "x", path="scripts/run.py", line=10),
        Finding("C5", "info", "y", path="bin/other.py", line=20),
    ]
    suppressions = [
        {"code": "C5", "path": "scripts/*.py", "reason": "x"},
    ]
    out = audit._apply_path_line_suppressions(findings, suppressions)
    assert len(out) == 1
    assert out[0].path == "bin/other.py"


def test_apply_path_line_filters_by_line_range():
    audit = _load_audit_module()
    Finding = audit.Finding
    findings = [
        Finding("C5", "info", "x", path="run.py", line=10),
        Finding("C5", "info", "y", path="run.py", line=20),
        Finding("C5", "info", "z", path="run.py", line=30),
    ]
    suppressions = [
        {"code": "C5", "path": "run.py", "line": "15-25", "reason": "x"},
    ]
    out = audit._apply_path_line_suppressions(findings, suppressions)
    assert len(out) == 2
    assert {f.line for f in out} == {10, 30}


def test_apply_path_line_empty_suppressions_is_passthrough():
    audit = _load_audit_module()
    Finding = audit.Finding
    findings = [Finding("C5", "info", "x", path="run.py", line=10)]
    out = audit._apply_path_line_suppressions(findings, [])
    assert out == findings


def test_apply_path_line_with_no_pathline_suppressions_is_passthrough():
    audit = _load_audit_module()
    Finding = audit.Finding
    findings = [Finding("C5", "info", "x", path="run.py", line=10)]
    suppressions = [{"code": "M2", "target": "tool", "reason": "x"}]
    out = audit._apply_path_line_suppressions(findings, suppressions)
    assert out == findings
