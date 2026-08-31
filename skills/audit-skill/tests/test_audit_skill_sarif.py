"""Unit tests for --sarif and --changed flags (PR-D).

SARIF tests exercise _render_sarif against representative Findings and
verify schema-correct structure (rules, results, regions, levels).
--changed tests cover the helper that resolves a git base ref into a
filtered skill set.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

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


def test_render_sarif_emits_schema_and_version():
    audit = _load_audit_module()
    out = audit._render_sarif([])
    d = json.loads(out)
    assert d["version"] == "2.1.0"
    assert "sarif-schema-2.1.0" in d["$schema"]
    assert len(d["runs"]) == 1


def test_render_sarif_maps_severity_to_level():
    audit = _load_audit_module()
    Finding = audit.Finding
    findings = [
        ("skill-a", Finding(code="H1", severity="drift", path="skills/a/SKILL.md",
                            line=10, msg="phantom citation: foo")),
        ("skill-a", Finding(code="C5", severity="info", path="skills/a/scripts/run.py",
                            line=5, msg="encoding missing")),
        ("skill-b", Finding(code="E0", severity="error", path="skills/b",
                            line=None, msg="skill directory not found: x")),
    ]
    d = json.loads(audit._render_sarif(findings))
    results = d["runs"][0]["results"]
    assert len(results) == 3
    by_rule = {r["ruleId"]: r for r in results}
    assert by_rule["H1"]["level"] == "warning"
    assert by_rule["C5"]["level"] == "note"
    assert by_rule["E0"]["level"] == "error"


def test_render_sarif_emits_region_for_line():
    audit = _load_audit_module()
    Finding = audit.Finding
    f = Finding(code="C2", severity="info", path="skills/a/SKILL.md",
                line=42, msg="POSIX-only path")
    d = json.loads(audit._render_sarif([("skill-a", f)]))
    loc = d["runs"][0]["results"][0]["locations"][0]
    assert loc["physicalLocation"]["region"]["startLine"] == 42


def test_render_sarif_omits_region_when_no_line():
    audit = _load_audit_module()
    Finding = audit.Finding
    f = Finding(code="H2", severity="info", path="skills/a/refs/foo.md",
                line=None, msg="orphan ref")
    d = json.loads(audit._render_sarif([("skill-a", f)]))
    physical = d["runs"][0]["results"][0]["locations"][0]["physicalLocation"]
    assert "region" not in physical


def test_render_sarif_deduplicates_rules():
    """Multiple findings with same code share one rule entry in tool.driver.rules."""
    audit = _load_audit_module()
    Finding = audit.Finding
    findings = [
        ("skill-a", Finding(code="C2", severity="info", path="a", line=1, msg="m1")),
        ("skill-b", Finding(code="C2", severity="info", path="b", line=2, msg="m2")),
        ("skill-c", Finding(code="C2", severity="info", path="c", line=3, msg="m3")),
    ]
    d = json.loads(audit._render_sarif(findings))
    rules = d["runs"][0]["tool"]["driver"]["rules"]
    assert len(rules) == 1
    assert rules[0]["id"] == "C2"
    assert len(d["runs"][0]["results"]) == 3


def test_render_sarif_normalizes_windows_paths():
    """Forward slashes in artifactLocation.uri per SARIF spec."""
    audit = _load_audit_module()
    Finding = audit.Finding
    f = Finding(code="C2", severity="info",
                path=r"skills\a\scripts\run.py", line=1, msg="x")
    d = json.loads(audit._render_sarif([("skill-a", f)]))
    uri = d["runs"][0]["results"][0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"]
    assert "\\" not in uri
    assert uri == "skills/a/scripts/run.py"


def test_skills_touched_since_returns_none_on_git_failure():
    audit = _load_audit_module()
    # Pass a ref that won't resolve — git returns non-zero, helper
    # returns None so caller can fall back to full set.
    result = audit._skills_touched_since("definitely-not-a-real-ref-xyz123")
    assert result is None


def test_skills_touched_since_extracts_skill_names():
    """When git returns paths, helper picks up skills/<name>/... only."""
    audit = _load_audit_module()
    fake_diff = "skills/audit-skill/SKILL.md\nskills/api-ingest/manifest.yaml\nbin/foo.py\nREADME.md\n"

    class FakeResult:
        returncode = 0
        stdout = fake_diff
        stderr = ""

    with patch.object(subprocess, "run", return_value=FakeResult()):
        result = audit._skills_touched_since("origin/main")
    assert result == {"audit-skill", "api-ingest"}


def test_skills_touched_since_ignores_non_skills_paths():
    """Changes outside skills/ don't add to the returned set."""
    audit = _load_audit_module()

    class FakeResult:
        returncode = 0
        stdout = "bin/audit-skill.py\nrules/foo.md\nhooks/bar.py\n"
        stderr = ""

    with patch.object(subprocess, "run", return_value=FakeResult()):
        result = audit._skills_touched_since("origin/main")
    assert result == set()
