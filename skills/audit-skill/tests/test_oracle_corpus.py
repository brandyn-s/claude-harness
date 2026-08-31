"""Layer C (corpus regression) tests.

Verifies:
  1. The corpus entries load without parse errors.
  2. Static check passes (codes well-formed, no required-vs-forbidden
     overlap, fixtures exist).
  3. Live check passes against the actual fixture skills — every
     required_code fires, no forbidden_code fires.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CORPUS_ROOT = Path(__file__).resolve().parent / "golden-findings"
FIXTURES_ROOT = Path(__file__).resolve().parent / "fixtures"


def _load_oracle():
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    for mod in ("oracle", "oracle.corpus"):
        if mod in sys.modules:
            del sys.modules[mod]
    from oracle import corpus  # noqa: E402
    return corpus


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_skill",
                                                    REPO / "bin" / "audit-skill.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_corpus_loads_with_expected_fixtures():
    corpus = _load_oracle()
    entries = corpus.load_corpus(CORPUS_ROOT)
    fixtures = {e.fixture for e in entries}
    # Each fixture skill under tests/fixtures/ that's expected to ship
    # a corpus entry must be represented.
    for required in ("clean-skill", "dirty-skill", "shell-only-skill",
                      "oversized-skill"):
        assert required in fixtures, (
            f"corpus missing entry for {required!r}; corpus entries are the "
            f"regression invariants for fixture-skill detection coverage"
        )


def test_corpus_static_check_passes():
    """Codes are well-formed; required/forbidden don't overlap;
    fixtures exist on disk."""
    corpus = _load_oracle()
    entries = corpus.load_corpus(CORPUS_ROOT)
    errors = corpus.check_corpus_static(entries, FIXTURES_ROOT)
    assert not errors, f"corpus static check found errors:\n  " + "\n  ".join(errors)


def test_corpus_live_check_passes():
    """Run Phase 1 audit against each fixture and compare against the
    corpus expectations. Catches Phase 1 detection regressions."""
    corpus_mod = _load_oracle()
    audit_mod = _load_audit_module()
    entries = corpus_mod.load_corpus(CORPUS_ROOT)

    # Warm canonical known-tools cache, then audit each fixture.
    original_skills = audit_mod.SKILLS
    audit_mod._KNOWN_TOOLS_CACHE = {}
    try:
        audit_mod.SKILLS = REPO / "skills"
        canonical = audit_mod._load_known_tools()
        audit_mod.SKILLS = FIXTURES_ROOT
        audit_mod._KNOWN_TOOLS_CACHE[str(FIXTURES_ROOT)] = canonical

        findings_by_fixture: dict[str, list[str]] = {}
        for entry in entries:
            f_list = audit_mod.audit(entry.fixture)
            findings_by_fixture[entry.fixture] = [f.code for f in f_list]
    finally:
        audit_mod.SKILLS = original_skills
        audit_mod._KNOWN_TOOLS_CACHE = {}

    results = corpus_mod.check_corpus_against_findings(entries, findings_by_fixture)
    failures = [r for r in results if not r.ok]
    if failures:
        lines = []
        for r in failures:
            lines.append(f"FAIL {r.fixture}")
            if r.missing_required:
                lines.append(f"  missing required: {r.missing_required}")
            if r.found_forbidden:
                lines.append(f"  observed forbidden: {r.found_forbidden}")
        assert False, "corpus live check failed:\n" + "\n".join(lines)
