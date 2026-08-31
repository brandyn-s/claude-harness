"""Contract regression tests for plugin-hook and MCP/skill discovery guards."""

from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


def test_audit_discovers_installed_plugin_hooks_without_enabled_only_blind_spot():
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    context = (SKILL_DIR / "audit-context.md").read_text(encoding="utf-8")
    combined = skill + "\n" + context

    assert "installed_plugins.json" in combined
    assert "installPath" in combined
    assert "disabled plugin" in combined.casefold()
    assert "_check_hooks_aux.py" in skill
    assert "known visibility limitation" not in combined.casefold()


def test_audit_runs_the_executable_mcp_skill_collision_guard():
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    context = (SKILL_DIR / "audit-context.md").read_text(encoding="utf-8")
    combined = skill + "\n" + context

    assert "skill/command runtime-name collision" in skill
    assert "_check_config.py" in skill
    assert "exact case-sensitive standalone" in combined
    assert "frontmatter `name`" in combined
    assert "legacy commands" in combined
    assert "plugin namespaces" in combined
    assert "Unicode-normalize" in combined
    assert "exact normalized" not in combined.casefold()


def test_audit_pins_plugin_state_precedence_and_manifest_shapes():
    skill = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    context = (SKILL_DIR / "audit-context.md").read_text(encoding="utf-8")
    combined = skill + "\n" + context

    assert "local > project > user" in combined
    assert "defaultEnabled" in combined
    assert "string/array/object" in combined
    assert "replaces the default" in combined
    assert "unknown" in combined
