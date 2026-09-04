"""Layer C — golden corpus for Phase 2 detection regression.

For each fixture skill in ``tests/fixtures/<skill>/`` we maintain an
``expected-findings.yaml`` (under ``tests/golden-findings/<skill>/``)
listing the codes Phase 2 SHOULD surface. The corpus catches the
class of regression where audit-skill stops noticing a known-bad
pattern.

Two granularities:

  required_codes: codes Phase 2 MUST surface. If any are missing,
    the test fails. These are the "must-find" invariants.

  forbidden_codes: codes Phase 2 must NOT surface. If any are
    present, the test fails. These catch false-positive regressions
    on patterns the corpus has classified as intentional.

Findings outside the union of required + forbidden are accepted
(neutral). This keeps the corpus from being a brittle exact-match
test while still pinning the high-value invariants.

The corpus check has two modes:

  static: just verify the YAML is well-formed.
  live: dispatch a Phase 2 agent against each fixture and grade
    findings against the corpus. Expensive — runs on demand, not
    in CI.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path


@dataclasses.dataclass
class CorpusEntry:
    """Per-fixture corpus contents."""
    fixture: str
    required_codes: list[str]
    forbidden_codes: list[str]
    notes: str = ""


def load_corpus(corpus_root: Path) -> list[CorpusEntry]:
    """Read all expected-findings.yaml under corpus_root and return as
    CorpusEntry list, sorted by fixture name."""
    entries: list[CorpusEntry] = []
    if not corpus_root.is_dir():
        return entries
    for sub in sorted(corpus_root.iterdir()):
        if not sub.is_dir():
            continue
        expected = sub / "expected-findings.yaml"
        if not expected.is_file():
            continue
        # Schema: { fixture: <name>, required_codes: [..], forbidden_codes: [..], notes: '...' }
        # The findings-format parser (oracle.finding._parse_minimal_yaml) does
        # not apply here; the corpus schema has its own minimal parser below.
        entries.append(_parse_corpus_entry(expected.read_text(encoding="utf-8"), sub.name))
    return entries


def _parse_corpus_entry(text: str, fallback_name: str) -> CorpusEntry:
    """Minimal parser for the corpus YAML schema (separate from
    findings format to keep both tiny)."""
    name = fallback_name
    required: list[str] = []
    forbidden: list[str] = []
    notes = ""
    current_list_key: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(r"^([a-zA-Z_]+):\s*(.*)$", stripped)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val:
                if key == "fixture":
                    name = val.strip('"\'')
                elif key == "notes":
                    notes = val.strip('"\'')
                current_list_key = None
            else:
                if key in ("required_codes", "forbidden_codes"):
                    current_list_key = key
                else:
                    current_list_key = None
            continue
        if stripped.startswith("- ") and current_list_key:
            val = stripped[2:].strip().strip('"\'')
            # Strip trailing inline-comment portion (YAML list values
            # may have `- CODE   # description` style annotations; the
            # corpus-entry codes are CODE only).
            if "#" in val:
                val = val.split("#", 1)[0].strip()
            if current_list_key == "required_codes":
                required.append(val)
            elif current_list_key == "forbidden_codes":
                forbidden.append(val)
    return CorpusEntry(fixture=name, required_codes=required,
                       forbidden_codes=forbidden, notes=notes)


@dataclasses.dataclass
class CorpusCheckResult:
    fixture: str
    missing_required: list[str]
    found_forbidden: list[str]

    @property
    def ok(self) -> bool:
        return not self.missing_required and not self.found_forbidden


def check_corpus_static(corpus: list[CorpusEntry], fixtures_root: Path) -> list[str]:
    """Static check: every corpus entry points to a real fixture, the
    required + forbidden sets are non-overlapping, and codes look
    well-formed. Returns a list of error strings (empty = OK)."""
    errors: list[str] = []
    code_pat = re.compile(r"^[A-Z][0-9a-z]+$")
    for entry in corpus:
        fixture_dir = fixtures_root / entry.fixture
        if not fixture_dir.is_dir():
            errors.append(
                f"corpus entry references fixture {entry.fixture!r} but "
                f"no directory at {fixture_dir}"
            )
        overlap = set(entry.required_codes) & set(entry.forbidden_codes)
        if overlap:
            errors.append(
                f"corpus entry {entry.fixture!r} has codes in BOTH required "
                f"and forbidden: {sorted(overlap)}"
            )
        for code in entry.required_codes + entry.forbidden_codes:
            if not code_pat.match(code):
                errors.append(
                    f"corpus entry {entry.fixture!r} has malformed code "
                    f"{code!r} (expected /[A-Z][0-9a-z]+/)"
                )
    return errors


def check_corpus_against_findings(
    corpus: list[CorpusEntry],
    findings_by_fixture: dict[str, list[str]],
) -> list[CorpusCheckResult]:
    """Compare a {fixture: [codes]} map (from live audit output)
    against the corpus. Returns one CorpusCheckResult per fixture."""
    results: list[CorpusCheckResult] = []
    for entry in corpus:
        observed = set(findings_by_fixture.get(entry.fixture, []))
        missing = [c for c in entry.required_codes if c not in observed]
        found_forbidden = [c for c in entry.forbidden_codes if c in observed]
        results.append(CorpusCheckResult(
            fixture=entry.fixture,
            missing_required=missing,
            found_forbidden=found_forbidden,
        ))
    return results
