"""Golden regression tests for audit-rules classify_rules.py.

The classifier is deterministic — no LLM involved — so full golden
regression is feasible. Tests are in three tiers:

  Unit tests: individual functions (hook_strength, discover_skill_rules,
    discover_uncovered_hooks) with isolated fixture roots.

  Golden regression: HOOK_RULE_MAP must reference only hooks that exist
    in the real repo. Catches stale entries when hooks are renamed/deleted.

  Integration test: full classify_rules() with a controlled fixture,
    verifying summary counts and layer assignments.

Re-run:
    pytest skills/audit-rules/tests/test_audit_rules_classifier.py -q

Fixture isolation: set AUDIT_RULES_CONFIG_ROOT before loading the module
to redirect CONFIG_ROOT (and therefore HOOKS_DIR, SKILLS_DIR, etc.)
to the fixture directory. Cleared after module load.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SKILL_DIR = Path(__file__).resolve().parent.parent


def _load_classifier(config_root=None):
    """Load classify_rules as a fresh module, with optional root override."""
    saved = os.environ.pop("AUDIT_RULES_CONFIG_ROOT", None)
    if config_root is not None:
        os.environ["AUDIT_RULES_CONFIG_ROOT"] = str(config_root)
    try:
        for key in list(sys.modules):
            if key == "classify_rules":
                del sys.modules[key]
        spec = importlib.util.spec_from_file_location(
            "classify_rules",
            SKILL_DIR / "references" / "classify_rules.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        os.environ.pop("AUDIT_RULES_CONFIG_ROOT", None)
        if saved is not None:
            os.environ["AUDIT_RULES_CONFIG_ROOT"] = saved
    return mod


def _make_fixture(root: Path) -> None:
    """Create a minimal controlled fixture layout."""
    hooks = root / "hooks"
    hooks.mkdir()
    (hooks / "enforced_hook.py").write_text(
        'import json, sys\nprint(json.dumps({"decision": "block"}))\n',
        encoding="utf-8",
    )
    (hooks / "warned_hook.py").write_text(
        'import json\nprint(json.dumps({"decision": "warn"}))\n',
        encoding="utf-8",
    )
    (hooks / "uncurated_enforced.py").write_text(
        'import json\nprint(json.dumps({"decision": "block"}))\n',
        encoding="utf-8",
    )
    skill_dir = root / "skills" / "test-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\n---\n"
        "## Step 1: Check `git branch --show-current` before committing.\n"
        '## Step 2: Always use encoding="utf-8" when opening files.\n',
        encoding="utf-8",
    )
    rules = root / "rules"
    rules.mkdir()
    (rules / "core.md").write_text(
        "- **Rule one**: do thing\n- **Rule two**: do other\n",
        encoding="utf-8",
    )
    settings = {
        "hooks": {
            "PreToolUse": [{"hooks": [
                {"command": "python /path/to/hooks/enforced_hook.py"},
                {"command": "python /path/to/hooks/warned_hook.py"},
            ]}],
        },
        "permissions": {},
    }
    (root / "settings.json").write_text(json.dumps(settings), encoding="utf-8")


# ── Unit: hook_strength ────────────────────────────────────────────────────────

def test_hook_strength_enforced(tmp_path):
    """Hook emitting decision:block → enforced."""
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "my_hook.py").write_text(
        'print(\'{"decision": "block"}\')\n', encoding="utf-8"
    )
    mod = _load_classifier(config_root=tmp_path)
    assert mod.hook_strength("my_hook.py") == "enforced"


def test_hook_strength_warned(tmp_path):
    """Hook emitting decision:warn → warned."""
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "my_hook.py").write_text(
        'print(\'{"decision": "warn"}\')\n', encoding="utf-8"
    )
    mod = _load_classifier(config_root=tmp_path)
    assert mod.hook_strength("my_hook.py") == "warned"


def test_hook_strength_sys_exit_2(tmp_path):
    """Hook using sys.exit(2) for blocking → enforced."""
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "my_hook.py").write_text(
        "import sys\nif bad:\n    sys.exit(2)\n", encoding="utf-8"
    )
    mod = _load_classifier(config_root=tmp_path)
    assert mod.hook_strength("my_hook.py") == "enforced"


def test_hook_strength_unknown_missing_file(tmp_path):
    """Non-existent hook file → unknown."""
    (tmp_path / "hooks").mkdir()
    mod = _load_classifier(config_root=tmp_path)
    assert mod.hook_strength("does_not_exist.py") == "unknown"


def test_hook_strength_permissions_deny(tmp_path):
    """permissions.deny is always enforced (no file read needed)."""
    (tmp_path / "hooks").mkdir()
    mod = _load_classifier(config_root=tmp_path)
    assert mod.hook_strength("permissions.deny") == "enforced"


# ── Unit: discover_skill_rules ─────────────────────────────────────────────────

def test_discover_skill_rules_branch_check(tmp_path):
    """SKILL.md with git branch --show-current → 'Check branch before commit'."""
    _make_fixture(tmp_path)
    mod = _load_classifier(config_root=tmp_path)
    rules = mod.discover_skill_rules()
    assert "test-skill" in rules
    assert "Check branch before commit" in rules["test-skill"]


def test_discover_skill_rules_encoding_utf8(tmp_path):
    """SKILL.md with encoding='utf-8' → 'Use encoding='utf-8' when opening files'."""
    _make_fixture(tmp_path)
    mod = _load_classifier(config_root=tmp_path)
    rules = mod.discover_skill_rules()
    assert "test-skill" in rules
    assert "Use encoding='utf-8' when opening files" in rules["test-skill"]


def test_discover_skill_rules_empty_when_no_markers(tmp_path):
    """SKILL.md with no recognized markers → skill absent from result."""
    skill_dir = tmp_path / "skills" / "plain-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: plain-skill\n---\n# Just some content, no markers.\n",
        encoding="utf-8",
    )
    (tmp_path / "hooks").mkdir()
    (tmp_path / "rules").mkdir()
    (tmp_path / "settings.json").write_text("{}", encoding="utf-8")
    mod = _load_classifier(config_root=tmp_path)
    rules = mod.discover_skill_rules()
    assert "plain-skill" not in rules


# ── Unit: discover_uncovered_hooks ─────────────────────────────────────────────

def test_discover_uncovered_hooks_finds_uncurated(tmp_path):
    """Hook with block signal not in curated map appears in uncovered list."""
    _make_fixture(tmp_path)
    mod = _load_classifier(config_root=tmp_path)
    curated = {
        "enforced_hook.py": ["Rule A"],
        "warned_hook.py": ["Rule B"],
        # uncurated_enforced.py intentionally absent
    }
    uncovered = mod.discover_uncovered_hooks(curated)
    names = [h for h, _ in uncovered]
    assert "uncurated_enforced.py" in names, (
        "uncurated_enforced.py has a block signal and is not in curated map"
    )


def test_discover_uncovered_hooks_curated_absent(tmp_path):
    """Hooks already in the curated map do not appear in uncovered list."""
    _make_fixture(tmp_path)
    mod = _load_classifier(config_root=tmp_path)
    curated = {
        "enforced_hook.py": ["Rule A"],
        "warned_hook.py": ["Rule B"],
        "uncurated_enforced.py": ["Rule C"],
    }
    uncovered = mod.discover_uncovered_hooks(curated)
    names = [h for h, _ in uncovered]
    assert "enforced_hook.py" not in names
    assert "warned_hook.py" not in names
    assert "uncurated_enforced.py" not in names


# ── Golden regression: production HOOK_RULE_MAP ───────────────────────────────

def test_hook_rule_map_references_real_hooks():
    """Every entry in HOOK_RULE_MAP must point to a hook that exists on disk.

    This test uses the real repo hooks directory (no fixture override).
    If a hook is renamed or deleted, this fails before audit-rules
    silently mis-classifies its rules as 'hook-enforced (unwired)'.
    """
    mod = _load_classifier()
    stale = mod.validate_hook_map(mod.HOOK_RULE_MAP)
    assert not stale, (
        f"HOOK_RULE_MAP references {len(stale)} hook(s) not on disk — "
        f"update HOOK_RULE_MAP in classify_rules.py:\n"
        + "\n".join(f"  {h}" for h in stale)
    )


# ── Unit: _RULE_UNIT (DSL-format rule counting) ────────────────────────────────

def test_rule_unit_matches_dsl_invariant_guard_failure():
    """REGRESSION (2026-07-04 review-learnings): _RULE_UNIT previously only
    recognized legacy '- **bold**' bullets, so a rules/*.md file written
    entirely in the current INVARIANT/GUARD/FAILURE DSL counted as having
    ZERO rules — undercounting total_rule_lines and therefore understating
    prompt_only_estimated. Must match all three DSL keywords, at minimum."""
    mod = _load_classifier()
    assert mod._RULE_UNIT.match("INVARIANT severity_follows_goal_classification")
    assert mod._RULE_UNIT.match('GUARD pattern="just give me the severity scores":')
    assert mod._RULE_UNIT.match("FAILURE severity_against_implicit_single_mode_target:")


def test_rule_unit_still_matches_legacy_bold_bullets():
    """GUARD-NOT-REGRESSED: the pre-existing legacy markdown convention
    ('- **Rule**' / '1. **Rule**') must still count — some rules/*.md
    files use it exclusively, and the fixture in _make_fixture relies on it."""
    mod = _load_classifier()
    assert mod._RULE_UNIT.match("- **Rule one**: do thing")
    assert mod._RULE_UNIT.match("1. **Numbered rule**: do thing")


def test_rule_unit_does_not_match_procedure_or_step_lines():
    """GUARD-NOT-TOO-BROAD: PROCEDURE headers and STEP_N lines are
    implementation detail of INVARIANTs declared elsewhere in the same
    file, not separate rules — counting them too would double-count the
    same behavioral constraint declaratively and operationally."""
    mod = _load_classifier()
    assert not mod._RULE_UNIT.match("PROCEDURE: before red-teaming a multi-mode artifact")
    assert not mod._RULE_UNIT.match("STEP_1 enumerate the artifact's modes")
    assert not mod._RULE_UNIT.match("  # WHY: severity is implicitly graded")


def test_classify_rules_counts_dsl_format_rule_file(tmp_path):
    """Integration: a rules/*.md file written entirely in DSL form (no
    legacy bold bullets) must contribute to total_rule_lines. Before the
    fix this fixture counted 0 additional rules from dsl.md; after the
    fix it counts 2 (one INVARIANT + one GUARD)."""
    _make_fixture(tmp_path)
    (tmp_path / "rules" / "dsl.md").write_text(
        "INVARIANT never_skip_the_framework\n"
        'GUARD pattern="skip it just this once":\n'
        "  REFUSE. NO EXCEPTIONS.\n",
        encoding="utf-8",
    )
    mod = _load_classifier(config_root=tmp_path)
    _, summary = mod.classify_rules()
    # core.md (2 legacy bullets) + dsl.md (1 INVARIANT + 1 GUARD) = 4
    assert summary["total_rule_lines"] == 4


# ── Integration: full classify_rules() ────────────────────────────────────────

def test_classify_rules_summary_counts_non_negative(tmp_path):
    """Full classify_rules() integration: summary counts are non-negative."""
    _make_fixture(tmp_path)
    mod = _load_classifier(config_root=tmp_path)
    _, summary = mod.classify_rules()
    for key in ("hook_enforced", "hook_warned", "skill_enforced", "prompt_only_estimated"):
        assert summary[key] >= 0, f"summary[{key!r}] is negative"


def test_classify_rules_skill_rules_appear_in_output(tmp_path):
    """Skill-enforced rules from the fixture appear in the classify_rules output."""
    _make_fixture(tmp_path)
    mod = _load_classifier(config_root=tmp_path)
    rules, _ = mod.classify_rules()
    skill_rules = [r for r in rules if r["layer"] == "skill-enforced"]
    assert skill_rules, (
        "expected at least one skill-enforced rule from the fixture SKILL.md markers"
    )


def test_classify_rules_json_output_schema(tmp_path):
    """Each rule entry has the required fields: rule, source, layer, hook_or_skill."""
    _make_fixture(tmp_path)
    mod = _load_classifier(config_root=tmp_path)
    rules, summary = mod.classify_rules()
    for r in rules:
        for field in ("rule", "source", "layer", "hook_or_skill"):
            assert field in r, f"rule entry missing field {field!r}: {r}"
