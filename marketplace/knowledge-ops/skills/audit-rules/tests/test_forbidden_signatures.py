"""Tests for extract_forbidden_signatures.py (Phase 7a).

Parses rules/*.md for snake_case FORBIDDEN identifiers and extracts
keyword signatures. These tests pin the parser against intentional
input shapes so a future rule edit doesn't silently break the
extractor.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "skills" / "audit-rules" / "scripts" / "extract_forbidden_signatures.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("extract_forbidden_signatures", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_extract_snake_case_identifier(tmp_path):
    """The canonical shape: FORBIDDEN: identifier_in_snake_case."""
    m = _load_module()
    rule_file = tmp_path / "test-rule.md"
    rule_file.write_text(
        "# test rule\n\n"
        "FORBIDDEN: pip_install_upgrade_all_outdated\n\n"
        "Long prose explanation...\n",
        encoding="utf-8",
    )
    sigs = m.extract_signatures_from_file(rule_file)
    assert len(sigs) == 1
    assert sigs[0]["identifier"] == "pip_install_upgrade_all_outdated"
    assert "pip" in sigs[0]["keywords"]
    assert "outdated" in sigs[0]["keywords"]
    assert sigs[0]["line"] == 3


def test_extract_drops_common_words(tmp_path):
    """Common English words (to, of, for, with, the) should be filtered
    out — too generic to be detector signals."""
    m = _load_module()
    rule_file = tmp_path / "r.md"
    rule_file.write_text(
        "FORBIDDEN: subprocess_run_text_true_for_external_apis\n",
        encoding="utf-8",
    )
    sigs = m.extract_signatures_from_file(rule_file)
    assert sigs[0]["keywords"] == ["subprocess", "run", "text", "true", "external", "apis"]
    assert "for" not in sigs[0]["keywords"]


def test_ignores_prose_forbidden(tmp_path):
    """FORBIDDEN: <free prose> is NOT a snake_case identifier — must
    be ignored so we don't try to keywordize natural language."""
    m = _load_module()
    rule_file = tmp_path / "r.md"
    rule_file.write_text(
        "FORBIDDEN: hypothesizing about the program without reading source\n"
        "FORBIDDEN: \"tests pass\" without citing evidence\n"
        "FORBIDDEN: this_is_snake_case\n",
        encoding="utf-8",
    )
    sigs = m.extract_signatures_from_file(rule_file)
    assert len(sigs) == 1
    assert sigs[0]["identifier"] == "this_is_snake_case"


def test_extracts_multiple_per_file(tmp_path):
    """A rule file may have many FORBIDDEN identifiers — all extracted."""
    m = _load_module()
    rule_file = tmp_path / "r.md"
    rule_file.write_text(
        "FORBIDDEN: alpha_beta\n\n"
        "stuff\n\n"
        "FORBIDDEN: gamma_delta\n\n"
        "more stuff\n\n"
        "FORBIDDEN: epsilon_zeta\n",
        encoding="utf-8",
    )
    sigs = m.extract_signatures_from_file(rule_file)
    assert len(sigs) == 3
    assert [s["identifier"] for s in sigs] == ["alpha_beta", "gamma_delta", "epsilon_zeta"]


def test_records_line_numbers(tmp_path):
    """Line numbers should be 1-indexed and accurate (operator uses
    them to navigate to the FORBIDDEN block)."""
    m = _load_module()
    rule_file = tmp_path / "r.md"
    rule_file.write_text(
        "# preamble\n"  # line 1
        "\n"             # line 2
        "FORBIDDEN: alpha\n"  # line 3
        "\n"             # line 4
        "more text\n"    # line 5
        "FORBIDDEN: beta\n",  # line 6
        encoding="utf-8",
    )
    sigs = m.extract_signatures_from_file(rule_file)
    assert sigs[0]["line"] == 3
    assert sigs[1]["line"] == 6


def test_cli_emits_json(tmp_path):
    """`--json` mode returns parseable JSON with rules/signatures shape."""
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "test1.md").write_text("FORBIDDEN: foo_bar\n", encoding="utf-8")
    (rules_dir / "test2.md").write_text("FORBIDDEN: baz_qux\n", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--rules-dir", str(rules_dir), "--json"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert len(data["rules"]) == 2
    names = {r["name"] for r in data["rules"]}
    assert names == {"test1", "test2"}


def test_cli_real_rules_dir_extracts_signatures():
    """Smoke test against the actual rules/ dir — must return a
    non-empty list (validates that the real corpus has at least
    some parseable FORBIDDEN identifiers)."""
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True, text=True,
        cwd=str(REPO),
    )
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    # At least 10 signatures across the real corpus
    total = sum(len(r["forbidden_signatures"]) for r in data["rules"])
    assert total >= 10, (
        f"expected >= 10 FORBIDDEN signatures in real rules/; got {total}"
    )


def test_ignores_indented_forbidden_lines(tmp_path):
    """FORBIDDEN must appear at column 0 (regex uses ^). Indented
    occurrences (inside code blocks, examples) are NOT extracted —
    they're documentation about the pattern, not the canonical
    forbidden declaration."""
    m = _load_module()
    rule_file = tmp_path / "r.md"
    rule_file.write_text(
        "  FORBIDDEN: not_extracted\n"  # leading spaces
        "FORBIDDEN: extracted\n",
        encoding="utf-8",
    )
    sigs = m.extract_signatures_from_file(rule_file)
    assert len(sigs) == 1
    assert sigs[0]["identifier"] == "extracted"
