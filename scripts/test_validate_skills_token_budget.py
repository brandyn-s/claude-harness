"""C1b_token_budget follows the corpus body-cap policy, not a private threshold.

docs/skill-cap-decisions.md sets a 6,000-token soft body cap (chars/4 proxy) that
scripts/token-audit.py enforces, with `metadata: {body-cap: exempt,
body-cap-reason: ...}` marking PERIODIC skills. Until 2026-09-04 the validator's
C1b check used its own 4,000-token threshold and ignored the exemption, failing
36 skills the policy accepted. These tests pin the alignment: one cap constant,
imported from token-audit rather than repeated; the exemption honoured (with a
reason, as in the audit); and a WORKFLOW skill over the cap still failing.

Written before the change and watched failing on the untouched validator.
"""
from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def validator():
    return _load("validate_skills_budget", "validate-skills.py")


@pytest.fixture(scope="module")
def token_audit():
    return _load("token_audit_budget", "token-audit.py")


FRONTMATTER = (
    "---\n"
    "name: fixture-skill\n"
    'description: "Use when exercising the body-cap check. Do NOT use for anything else."\n'
    "{metadata}"
    "---\n"
)
EXEMPT = 'metadata:\n  body-cap: exempt\n  body-cap-reason: "PERIODIC: a weekly report"\n'
EXEMPT_NO_REASON = "metadata:\n  body-cap: exempt\n"


def _skill(tmp_path: Path, tokens: int, metadata: str = "") -> Path:
    """A skill whose whole SKILL.md measures exactly `tokens` on the chars/4 proxy."""
    skill_dir = tmp_path / "fixture-skill"
    skill_dir.mkdir()
    head = FRONTMATTER.format(metadata=metadata) + "\n## Step 1\n\n1. Do the thing.\n\n"
    filler = tokens * 4 - len(head)
    assert filler > 0
    text = head + ("filler text " * (filler // 12 + 1))[:filler]
    (skill_dir / "SKILL.md").write_text(text, encoding="utf-8")
    return skill_dir


def _c1b(validator, skill_dir: Path) -> tuple[bool, str]:
    checks, notes = validator.score_skill(skill_dir)
    return checks["C1b_token_budget"], notes.get("C1b", "")


def test_cap_is_token_audits_constant_not_a_private_number(validator, token_audit):
    assert validator.SOFT_BODY_CAP == token_audit.SOFT_BODY_CAP == 6000
    # Code constants only (comments may recount the history): neither the retired
    # 4,000 threshold nor a repeated 6,000 may appear as a literal in the validator.
    tree = ast.parse((ROOT / "scripts" / "validate-skills.py").read_text(encoding="utf-8"))
    literals = {
        node.value for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, int)
    }
    assert 4000 not in literals, "the retired private threshold is back"
    assert 6000 not in literals, "the cap is imported from token-audit, not repeated"


def test_body_between_the_old_threshold_and_the_cap_passes(validator, tmp_path):
    ok, note = _c1b(validator, _skill(tmp_path, tokens=5000))
    assert ok, note


def test_exempt_periodic_skill_over_the_cap_passes(validator, tmp_path):
    ok, note = _c1b(validator, _skill(tmp_path, tokens=7000, metadata=EXEMPT))
    assert ok, note
    assert "exempt" in note and "PERIODIC" in note


def test_workflow_skill_over_the_cap_fails(validator, token_audit, tmp_path):
    skill_dir = _skill(tmp_path, tokens=7000)
    ok, note = _c1b(validator, skill_dir)
    assert not ok
    measured = int(re.search(r"body_proxy=(\d+)", note).group(1))
    assert measured == token_audit.estimate_tokens((skill_dir / "SKILL.md").read_text(encoding="utf-8")), (
        "the validator and the audit must measure the same number"
    )


def test_exemption_without_a_reason_still_counts(validator, tmp_path):
    """Mirrors token-audit: `exempt-missing-reason` keeps counting against the cap."""
    ok, note = _c1b(validator, _skill(tmp_path, tokens=7000, metadata=EXEMPT_NO_REASON))
    assert not ok
    assert "reason" in note
