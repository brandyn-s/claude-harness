"""Fixture-corpus tests for audit-skill check categories.

Each check (H1, H4, D3a, D3b, D3c, M2, T1, C2, …) is exercised against
a known-good fixture (clean-skill — must produce zero findings) and a
known-bad fixture (dirty-skill — must produce specific finding codes).

This is the "fixture-corpus before shipping" discipline distilled in
agent-memory/topics/engineering-philosophy.md "Audit + dev-tooling
discipline" — without it, regressions in audit-skill's detection
logic ship silently because we only ever sanity-check against the
production tree.
"""

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
AUDIT_SCRIPT = REPO / "bin" / "audit-skill.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load_audit_module():
    if "audit_skill" in sys.modules:
        return sys.modules["audit_skill"]
    spec = importlib.util.spec_from_file_location("audit_skill", AUDIT_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules["audit_skill"] = mod
    return mod


def _audit_fixture(fixture_name):
    """Run audit() against a fixture by temporarily redirecting the
    module-level SKILLS path. Returns the list[Finding].

    The cache is keyed by SKILLS, so we pre-populate the cache entry
    for the fixture root using the canonical known-tools.yaml (loaded
    against REPO/skills first). Without this, T1 has no phantom list
    when SKILLS points at fixtures/ (where no known-tools.yaml lives)."""
    audit = _load_audit_module()
    fixture_root = FIXTURES
    fixture_dir = fixture_root / fixture_name
    assert fixture_dir.is_dir(), f"fixture missing: {fixture_dir}"
    original_skills = audit.SKILLS
    audit._KNOWN_TOOLS_CACHE = {}
    # Load the canonical registry first (with SKILLS pointing at the
    # real tree).
    audit.SKILLS = REPO / "skills"
    canonical_entry = audit._load_known_tools()
    # Now point SKILLS at the fixture root and copy the canonical entry
    # into the cache under the fixture-root key so T1 still has the
    # registry to consult.
    audit.SKILLS = fixture_root
    audit._KNOWN_TOOLS_CACHE[str(fixture_root)] = canonical_entry
    try:
        return audit.audit(fixture_name)
    finally:
        audit.SKILLS = original_skills
        audit._KNOWN_TOOLS_CACHE = {}


def test_clean_skill_produces_zero_findings():
    """clean-skill is the known-good fixture — every check must let it
    through cleanly. If this regresses, an audit-skill change has
    started false-positiving on well-formed input."""
    findings = _audit_fixture("clean-skill")
    drift = [f for f in findings if f.severity == "drift"]
    info = [f for f in findings if f.severity == "info"]
    err = [f for f in findings if f.severity == "error"]
    msgs = "\n".join(f"  {f}" for f in findings)
    assert not drift, f"clean fixture produced unexpected drift:\n{msgs}"
    assert not err, f"clean fixture produced errors:\n{msgs}"
    assert not info, f"clean fixture produced unexpected info findings:\n{msgs}"


def test_dirty_skill_fires_expected_checks():
    """dirty-skill is the known-bad fixture — the listed check codes
    MUST fire. If a check stops firing, the detection logic has
    regressed."""
    findings = _audit_fixture("dirty-skill")
    codes = {f.code for f in findings}
    # The dirty fixture intentionally triggers these:
    expected = {
        "H1",   # references/missing-ref.md cited but missing
        "H4",   # nonexistent-skill/references/foo.md
        "H5",   # phantom-dir/MISSING.md cited with "read" verb but missing
        "D3a",  # python ~/.claude/skills/dirty-skill/scripts/missing.py
        "D3b",  # ${CLAUDE_SKILL_DIR}/scripts/run.py
        "D3c",  # scripts/orphan.py never referenced
        "M2",   # mcp__unused__never_invoked declared but unused
        "M3",   # manifest.yaml has # TODO placeholder
        "M4",   # MCP tools in allowed-tools missing from manifest requires_tools
        "T1",   # mcp__code-graph__index_status (known-phantom)
        "C2",   # /tmp/ in bash docs
        "C5",   # run.py: .read_text() without encoding='utf-8'
        "C6",   # run.py: argparse help with unescaped `25%`
        "C7",   # orphan.py: __main__ + sys.argv, no --help short-circuit
    }
    missing = expected - codes
    assert not missing, (
        f"dirty fixture failed to trigger expected checks: {sorted(missing)}\n"
        f"observed codes: {sorted(codes)}\n"
        f"findings:\n" + "\n".join(f"  {f}" for f in findings)
    )


def test_dirty_skill_does_not_fire_d3a_on_real_script():
    """The fixture has both a real `scripts/run.py` AND a documented
    nonexistent `scripts/missing.py`. D3a must flag the missing one
    but NOT the present one. Catches a regression where every script
    path becomes a finding regardless of disk presence."""
    findings = _audit_fixture("dirty-skill")
    d3a_messages = [f.msg for f in findings if f.code == "D3a"]
    assert any("missing.py" in m for m in d3a_messages), (
        f"D3a should flag missing.py; got: {d3a_messages}"
    )
    assert not any("run.py" in m and "missing" not in m for m in d3a_messages), (
        f"D3a falsely flagged run.py (which DOES exist); got: {d3a_messages}"
    )


def test_output_schema_for_clean_fixture_is_stable():
    """Pin audit-skill's output for the clean fixture. The clean fixture
    produces zero findings; the output is the single OK line. Any
    output-format change downstream tooling depends on (CI parsers,
    dashboards, badges) will be caught here.

    To regenerate: run this test, capture the assertion error, paste
    the actual output into the expected string."""
    import io
    audit = _load_audit_module()
    original_skills = audit.SKILLS
    audit._KNOWN_TOOLS_CACHE = {}
    audit.SKILLS = REPO / "skills"
    canonical_entry = audit._load_known_tools()
    audit.SKILLS = FIXTURES
    audit._KNOWN_TOOLS_CACHE[str(FIXTURES)] = canonical_entry
    try:
        findings = audit.audit("clean-skill")
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            audit.report("clean-skill", findings)
        finally:
            sys.stdout = old_stdout
        output = buf.getvalue()
    finally:
        audit.SKILLS = original_skills
        audit._KNOWN_TOOLS_CACHE = {}
    expected = "OK   clean-skill\n"
    assert output == expected, (
        f"clean-skill output schema regressed.\n"
        f"expected: {expected!r}\n"
        f"actual:   {output!r}"
    )


def test_output_schema_for_dirty_fixture_is_stable():
    """Pin audit-skill's output FORMAT for the dirty fixture. We don't
    pin exact bytes (findings reorder slightly between runs based on
    iteration order) but DO pin the shape: header line + indented
    finding lines + finding-message lines + counts."""
    import io
    audit = _load_audit_module()
    original_skills = audit.SKILLS
    audit._KNOWN_TOOLS_CACHE = {}
    audit.SKILLS = REPO / "skills"
    canonical_entry = audit._load_known_tools()
    audit.SKILLS = FIXTURES
    audit._KNOWN_TOOLS_CACHE[str(FIXTURES)] = canonical_entry
    try:
        findings = audit.audit("dirty-skill")
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            audit.report("dirty-skill", findings)
        finally:
            sys.stdout = old_stdout
        output = buf.getvalue()
    finally:
        audit.SKILLS = original_skills
        audit._KNOWN_TOOLS_CACHE = {}

    lines = output.splitlines()
    # Header: "FAIL dirty-skill: N drift, M error, K info"
    assert lines[0].startswith("FAIL dirty-skill:"), (
        f"header format changed: {lines[0]!r}"
    )
    assert "drift" in lines[0] and "info" in lines[0] and "error" in lines[0]

    # Each finding is 2 lines: "  CODE [severity] [path:line]"
    # then "      message"
    import re
    code_line_pat = re.compile(r"^  [A-Z][0-9a-z]+ \[(drift|info|error)\] \[.+?\]")
    msg_line_pat = re.compile(r"^      \S")
    code_lines = [l for l in lines[1:] if code_line_pat.match(l)]
    msg_lines = [l for l in lines[1:] if msg_line_pat.match(l)]
    assert code_lines, "no finding code lines found in output"
    assert len(msg_lines) == len(code_lines), (
        f"finding-line/message-line count mismatch: "
        f"{len(code_lines)} codes vs {len(msg_lines)} messages"
    )


def test_json_output_emits_valid_json_with_expected_shape(tmp_path):
    """`--json` produces machine-readable output: one JSON object per
    skill on stdout, with fields {skill, status, counts, findings}.
    Catches drift in the contract that CI tooling depends on."""
    import json
    import subprocess
    r = subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT), "audit-skill", "--json",
         "--no-marketplace-check"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"audit failed: {r.stderr}"
    obj = json.loads(r.stdout.strip())
    assert obj["skill"] == "audit-skill"
    assert obj["status"] in ("OK", "INFO", "FAIL")
    assert set(obj["counts"]) == {"drift", "info", "error"}
    assert isinstance(obj["findings"], list)


def test_every_finding_code_has_a_fixture_trigger():
    """The "fixture-corpus before shipping" discipline encoded as a test:
    every Finding code emitted by audit-skill.py MUST be triggered by
    at least one fixture under tests/fixtures/. Catches the case where
    a check exists in code but no test exercises its trigger — the
    pattern that hid latent bugs in --strict-tools for months."""
    import re
    audit_py = AUDIT_SCRIPT.read_text(encoding="utf-8")
    code_pat = re.compile(r'Finding\(\s*"([A-Z][0-9a-z]+)"')
    codes = sorted(set(code_pat.findall(audit_py)))
    # E0: internal "skill not found" error code; can't be triggered by
    # a fixture (it's a missing-skill case).
    # B2: repo-wide check on hooks/ ↔ hooks/test-hooks/ coverage. Fires
    # in the `__repo__` pass at `--all` time, not per-skill, so it has
    # no skill-fixture trigger. The dedicated `test_b2_*` unit tests in
    # test_audit_skill_helpers.py cover it instead.
    excluded = {"E0", "B2"}

    # Aggregate observed codes across all fixtures.
    audit = _load_audit_module()
    observed = set()
    if FIXTURES.is_dir():
        for fixture_dir in FIXTURES.iterdir():
            if not fixture_dir.is_dir():
                continue
            findings = _audit_fixture(fixture_dir.name)
            observed.update(f.code for f in findings)

    missing = [c for c in codes if c not in observed and c not in excluded]
    assert not missing, (
        f"Finding code(s) defined in audit-skill.py but NOT triggered by "
        f"any fixture: {missing}. Add a fixture in "
        f"skills/audit-skill/tests/fixtures/ that triggers each code. "
        f"This is the fixture-corpus discipline: every check must be "
        f"exercised by at least one input."
    )
