"""Layer C (corpus regression) tests for audit-architecture.

Static check verifies:
  - corpus YAML files load without parse errors
  - all fixture entries point to real directories
  - required_codes and forbidden_codes are well-formed and non-overlapping
  - true_fixture has required_codes; false_fixture has forbidden_codes

Live check (test_corpus_live_check_passes) runs the deterministic
fixture_auditor.py against each fixture and grades against the corpus.
This catches detection regressions without dispatching a Phase 2 LLM agent.

Re-run:
    pytest skills/audit-architecture/tests/test_audit_architecture_corpus.py -q

Corpus root:   skills/audit-architecture/tests/golden-findings/
Fixtures root: skills/audit-architecture/tests/golden-findings/calibration/
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
# expected-findings.yaml files live one level under this directory
CORPUS_ROOT = Path(__file__).resolve().parent / "golden-findings"
# fixture dirs live under calibration/
FIXTURES_ROOT = Path(__file__).resolve().parent / "golden-findings" / "calibration"


def _load_corpus():
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for mod in list(sys.modules):
        if mod in ("oracle", "oracle.corpus"):
            del sys.modules[mod]
    from oracle import corpus
    return corpus


def test_corpus_loads_with_expected_fixtures():
    """Both fixture corpus entries parse without errors."""
    corpus = _load_corpus()
    entries = corpus.load_corpus(CORPUS_ROOT)
    fixtures = {e.fixture for e in entries}
    for name in ("true_fixture", "false_fixture"):
        assert name in fixtures, (
            f"corpus missing entry for {name!r} — expected "
            f"tests/golden-findings/{name}/expected-findings.yaml"
        )


def test_corpus_static_check_passes():
    """Codes are well-formed ([A-Z][0-9a-z]+), required and forbidden sets
    don't overlap, and each fixture directory exists under calibration/."""
    corpus = _load_corpus()
    entries = corpus.load_corpus(CORPUS_ROOT)
    errors = corpus.check_corpus_static(entries, FIXTURES_ROOT)
    assert not errors, (
        "corpus static check found errors:\n  " + "\n  ".join(errors)
    )


def test_true_fixture_has_required_codes():
    """true_fixture must define required_codes — it has deliberate bugs."""
    corpus = _load_corpus()
    entries = corpus.load_corpus(CORPUS_ROOT)
    entry = next((e for e in entries if e.fixture == "true_fixture"), None)
    assert entry is not None
    assert entry.required_codes, (
        "true_fixture corpus entry has no required_codes; add the codes "
        "that Phase 2 MUST surface for the known bugs in that fixture"
    )


def test_false_fixture_has_forbidden_codes():
    """false_fixture must define forbidden_codes — it has no bugs."""
    corpus = _load_corpus()
    entries = corpus.load_corpus(CORPUS_ROOT)
    entry = next((e for e in entries if e.fixture == "false_fixture"), None)
    assert entry is not None
    assert entry.forbidden_codes, (
        "false_fixture corpus entry has no forbidden_codes; add the codes "
        "that Phase 2 must NOT surface on a clean architecture fixture"
    )


def test_required_and_forbidden_are_consistent():
    """Codes required in true_fixture should be forbidden in false_fixture."""
    corpus = _load_corpus()
    entries = corpus.load_corpus(CORPUS_ROOT)
    by_fixture = {e.fixture: e for e in entries}
    true_entry = by_fixture.get("true_fixture")
    false_entry = by_fixture.get("false_fixture")
    if not (true_entry and false_entry):
        pytest.skip("both fixture entries required for consistency check")
    missing = set(true_entry.required_codes) - set(false_entry.forbidden_codes)
    assert not missing, (
        f"codes required in true_fixture but not forbidden in false_fixture: "
        f"{sorted(missing)} — add them to false_fixture.forbidden_codes so the "
        f"corpus enforces both halves of each bug"
    )


def test_corpus_live_check_passes():
    """Run the deterministic fixture_auditor against each fixture and
    grade against the corpus. Catches detection regressions without
    dispatching a Phase 2 LLM agent."""
    import subprocess
    import json

    corpus_mod = _load_corpus()
    entries = corpus_mod.load_corpus(CORPUS_ROOT)

    auditor = REPO / "skills" / "audit-architecture" / "references" / "fixture_auditor.py"
    findings_by_fixture = {}
    for entry in entries:
        fixture_dir = FIXTURES_ROOT / entry.fixture
        r = subprocess.run(
            [sys.executable, str(auditor), str(fixture_dir)],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, (
            f"fixture_auditor crashed on {entry.fixture}:\n{r.stderr}"
        )
        data = json.loads(r.stdout)
        findings_by_fixture[entry.fixture] = data["codes"]

    results = corpus_mod.check_corpus_against_findings(entries, findings_by_fixture)
    failures = [res for res in results if not res.ok]
    if failures:
        lines = []
        for res in failures:
            lines.append(f"FAIL {res.fixture}")
            if res.missing_required:
                lines.append(f"  missing required: {res.missing_required}")
            if res.found_forbidden:
                lines.append(f"  observed forbidden: {res.found_forbidden}")
        assert False, "corpus live check failed:\n" + "\n".join(lines)
