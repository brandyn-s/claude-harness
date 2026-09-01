"""Regression tests for manifest scaffolding from current hook exec form."""

from __future__ import annotations

import json

from manifests import scaffold


def test_scaffold_hook_discovers_exec_form_registration(tmp_path, monkeypatch):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    (hooks / "guard.py").write_text('"""Guard a test operation."""\n', encoding="utf-8")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "hooks": {"PreToolUse": [{
            "matcher": "Bash",
            "hooks": [{
                "type": "command",
                "command": str(hooks / "run-hook"),
                "args": ["guard.py"],
            }],
        }]},
    }), encoding="utf-8")
    monkeypatch.setattr(scaffold, "HOOKS_DIR", hooks)
    monkeypatch.setattr(scaffold, "SETTINGS_FILE", settings)

    result = scaffold.scaffold_hook("guard", dry_run=True)

    assert result is not None
    assert result["event"] == "PreToolUse"
    assert 'matcher: "Bash"' in result["content"]


def test_rule_scaffold_omits_compiler_derived_enforced_by(tmp_path, monkeypatch):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "safety.md").write_text("# Safety\n", encoding="utf-8")
    monkeypatch.setattr(scaffold, "RULES_DIR", rules)

    result = scaffold.scaffold_rule("safety", dry_run=True)

    assert result is not None
    assert "enforced_by" not in result["content"]
    assert "enforcement_coverage: none" in result["content"]
