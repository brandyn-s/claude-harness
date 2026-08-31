"""Unit tests for healthcheck/references/_check_skills.py — iteration filter.

Pins the dot-directory skip fix. A stray HIDDEN dir in skills/ (e.g.
.pytest_cache, .DS_Store, .ipynb_checkpoints) is NOT a skill and must be
SKIPPED, not flagged as a Tier-A "SKILL.md missing" FAIL (the most severe
healthcheck outcome). Before the fix the iteration skipped only
`_`-prefixed dirs, so a `.pytest_cache` dropped into skills/ by a pytest
run produced a false Tier-A FAIL.
"""
import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hc_check_skills",
    Path(__file__).resolve().parent.parent / "references" / "_check_skills.py",
)
hc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hc)


VALID_SKILL = """\
---
name: {name}
description: A valid skill that does a thing and is used when testing it.
---

# {name}

## Examples
An example.

## Success Criteria
- It works.
"""


def _make_skill(skills_dir, name):
    d = skills_dir / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(VALID_SKILL.format(name=name), encoding="utf-8")


def _run(monkeypatch, skills_dir, capsys):
    monkeypatch.setattr(hc, "SKILLS_DIR", skills_dir)
    rc = hc.check_skills()
    return rc, capsys.readouterr().out


def test_dot_dir_is_skipped_not_failed(tmp_path, monkeypatch, capsys):
    skills = tmp_path / "skills"
    skills.mkdir()
    _make_skill(skills, "realskill")
    (skills / ".pytest_cache").mkdir()          # debris a pytest run can drop
    rc, out = _run(monkeypatch, skills, capsys)
    assert rc == 0, f"expected PASS, got rc={rc}\n{out}"
    assert ".pytest_cache" in out               # reported as a skipped helper dir
    assert "FAIL" not in out


def test_underscore_dir_still_skipped(tmp_path, monkeypatch, capsys):
    skills = tmp_path / "skills"
    skills.mkdir()
    _make_skill(skills, "realskill")
    (skills / "_shared").mkdir()
    rc, out = _run(monkeypatch, skills, capsys)
    assert rc == 0
    assert "_shared" in out


def test_real_missing_skillmd_still_fails(tmp_path, monkeypatch, capsys):
    # A NON-hidden dir without SKILL.md is a genuine Tier-A FAIL — the fix
    # must not suppress this.
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "brokenskill").mkdir()
    rc, out = _run(monkeypatch, skills, capsys)
    assert rc == 2
    assert "brokenskill" in out and "SKILL.md missing" in out


def test_dot_dir_skipped_even_amid_real_failure(tmp_path, monkeypatch, capsys):
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "brokenskill").mkdir()            # real Tier-A FAIL
    (skills / ".ipynb_checkpoints").mkdir()     # hidden — must still be skipped
    rc, out = _run(monkeypatch, skills, capsys)
    assert rc == 2                              # the real failure still fails
    assert ".ipynb_checkpoints: SKILL.md missing" not in out


def test_long_body_is_warn_not_tier_a_fail(tmp_path, monkeypatch, capsys):
    """2026-06-28: SKILL.md body length is a SOFT cap (skill-standards.md ≤510,
    non-failing). A >510-line body is a WARN (rc 1), NOT a Tier-A FAIL (rc 2) —
    aligns the helper with validate-skills.py C1 + 'do NOT tighten to a hard 500'."""
    skills = tmp_path / "skills"
    skills.mkdir()
    d = skills / "longskill"
    d.mkdir()
    long_body = VALID_SKILL.format(name="longskill") + "\n".join(
        f"# filler {i}" for i in range(540))
    (d / "SKILL.md").write_text(long_body, encoding="utf-8")
    rc, out = _run(monkeypatch, skills, capsys)
    assert rc == 1, f"long body must be WARN (rc 1), not Tier-A FAIL (rc 2); got rc={rc}\n{out[:300]}"
    assert "longskill" in out and ("510" in out or "soft cap" in out.lower())


def test_worked_example_heading_satisfies_examples_check(tmp_path, monkeypatch, capsys):
    """2026-08-22: CI's validate-skills.py accepts any heading CONTAINING
    'example' (EXAMPLE_HEADER_RE). The local prefix-anchored regex was
    STRICTER than CI and Tier-A-FAILed `## Worked example` — a skill CI
    shipped. The local check must accept what CI accepts."""
    skills = tmp_path / "skills"
    skills.mkdir()
    d = skills / "workedskill"
    d.mkdir()
    body = VALID_SKILL.format(name="workedskill").replace(
        "## Examples", "## Worked example — one full cycle")
    (d / "SKILL.md").write_text(body, encoding="utf-8")
    rc, out = _run(monkeypatch, skills, capsys)
    assert rc == 0, f"'## Worked example' must satisfy the Examples check\n{out}"


def test_tier_a_does_not_mask_tier_bc(tmp_path, monkeypatch, capsys):
    """2026-08-22: the old `elif` reported only Tier-A for a skill that also
    had Tier-B/C issues, so fixing the Tier-A 'revealed' warns that read as
    regressions. Both tiers must report in one pass."""
    skills = tmp_path / "skills"
    skills.mkdir()
    d = skills / "bothskill"
    d.mkdir()
    # No Examples (Tier-A) AND no Success Criteria (Tier-C) in the same skill.
    (d / "SKILL.md").write_text(
        "---\nname: bothskill\ndescription: does a thing.\n---\n\n# bothskill\nbody\n",
        encoding="utf-8")
    rc, out = _run(monkeypatch, skills, capsys)
    assert rc == 2
    assert "no `## Examples` section" in out
    assert "no `## Success Criteria` section" in out, \
        f"Tier-B/C finding masked by Tier-A failure\n{out}"


def test_reserved_exceptions_match_ci_validator():
    """The reserved-name exemption list is single-sourced from CI's
    scripts/validate-skills.py EXEMPT_NAMES (2026-08-22: a hand-copied
    second list drifted and FAILed a skill CI shipped). When the validator
    exists on this host, the loaded set must equal its literal."""
    import ast
    validator = hc.CLAUDE_DIR / "scripts" / "validate-skills.py"
    if not validator.is_file():
        import pytest
        pytest.skip("CI validator not present on this host")
    exempt = None
    for node in ast.walk(ast.parse(validator.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "EXEMPT_NAMES":
                    exempt = set(ast.literal_eval(node.value))
    assert exempt, "EXEMPT_NAMES literal not found in validator"
    assert hc.LOCAL_RESERVED_EXCEPTIONS == exempt
