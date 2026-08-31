"""Unit tests for healthcheck/references/_check_hooks_aux.py.

Pins the hook-vs-helper classifier. A file counts toward the coverage and
error-handling denominators only if it FIRES as a hook — registered in
settings.json OR reads stdin. Imported helper modules (no stdin, unregistered)
are excluded; counting them produced false WARNs (2026-06-16: `_platform.py`
flagged for no try/except, 4 helpers flagged "untested").
"""

import importlib.util
import json
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hc_check_hooks_aux",
    Path(__file__).resolve().parent.parent / "references" / "_check_hooks_aux.py",
)
assert _SPEC and _SPEC.loader
hc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hc)

STDIN_TRY = (
    "import sys\ntry:\n    data = sys.stdin.read()\nexcept Exception:\n    pass\n"
)
STDIN_NOTRY = "import sys\ndata = sys.stdin.read()\n"
HELPER_BODY = "def util():\n    return 1\n"
NOSTDIN_TRY = "x = 1\ntry:\n    x = 2\nexcept Exception:\n    pass\n"


def _run(tmp_path, monkeypatch, capsys, hooks, tests=(), registered=()):
    claude = tmp_path / ".claude"
    hooksd = claude / "hooks"
    testsd = hooksd / "test-hooks"
    testsd.mkdir(parents=True)
    for fn, body in hooks.items():
        (hooksd / fn).write_text(body, encoding="utf-8")
    for t in tests:
        (testsd / t).write_text("def test_x():\n    pass\n", encoding="utf-8")
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [
                        {"command": f"python3 $HOME/.claude/hooks/{c}"}
                        for c in registered
                    ]
                }
            ]
        }
    }
    (claude / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    monkeypatch.setattr(hc, "H", str(claude))
    monkeypatch.setattr(hc, "HOOKS", str(hooksd))
    monkeypatch.setattr(hc, "TESTS", str(testsd))
    rc = hc.main()
    return rc, capsys.readouterr().out


def test_helper_module_excluded_not_untested(tmp_path, monkeypatch, capsys):
    # THE BUG: a no-stdin, unregistered helper must NOT count as an untested hook.
    rc, out = _run(
        tmp_path,
        monkeypatch,
        capsys,
        hooks={"realhook.py": STDIN_TRY, "_platform.py": HELPER_BODY},
        tests=["test_realhook.py"],
    )
    assert rc == 0, out
    assert "1/1 hooks have tests" in out
    assert "helper modules excluded" in out
    assert "_platform.py" in out  # listed as excluded helper
    assert "untested hook: _platform.py" not in out


def test_stdin_hook_without_test_flagged(tmp_path, monkeypatch, capsys):
    rc, out = _run(tmp_path, monkeypatch, capsys, hooks={"orphanhook.py": STDIN_TRY})
    assert rc == 1
    assert "untested hook: orphanhook.py" in out


def test_registered_no_stdin_hook_is_counted(tmp_path, monkeypatch, capsys):
    # A registered hook that doesn't read stdin is still a hook, not a helper.
    rc, out = _run(
        tmp_path,
        monkeypatch,
        capsys,
        hooks={"reghook.py": NOSTDIN_TRY},
        tests=["test_reghook.py"],
        registered=["reghook.py"],
    )
    assert rc == 0, out
    assert "1/1 hooks have tests" in out  # counted (1 hook), not excluded


def test_stdin_hook_missing_try_flagged(tmp_path, monkeypatch, capsys):
    rc, out = _run(
        tmp_path,
        monkeypatch,
        capsys,
        hooks={"unsafehook.py": STDIN_NOTRY},
        tests=["test_unsafehook.py"],
    )
    assert rc == 1
    assert "missing try/except: unsafehook.py" in out


def test_clean_hook_passes(tmp_path, monkeypatch, capsys):
    rc, out = _run(
        tmp_path,
        monkeypatch,
        capsys,
        hooks={"goodhook.py": STDIN_TRY},
        tests=["test_goodhook.py"],
    )
    assert rc == 0
    assert "Hook error handling: PASS" in out


# --- check_matcher_schema (A3, #75071/#75081: a schema-invalid matcher silently
#     disables ALL settings.json hooks). ------------------------------------------


def _schema(tmp_path, monkeypatch, hooks_obj):
    claude = tmp_path / ".claude"
    claude.mkdir(parents=True, exist_ok=True)
    (claude / "settings.json").write_text(
        json.dumps({"hooks": hooks_obj}), encoding="utf-8"
    )
    monkeypatch.setattr(hc, "H", str(claude))
    return hc.check_matcher_schema()


def test_matcher_schema_clean_command_and_prompt(tmp_path, monkeypatch):
    # Regression guard: an earlier draft required type=='command' and flagged every
    # prompt hook — our live settings.json uses both types (2026-07-08 known-negative).
    problems = _schema(
        tmp_path,
        monkeypatch,
        {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "run x"}]},
                {
                    "matcher": "mcp__a__b|mcp__c__d",
                    "hooks": [{"type": "prompt", "prompt": "gate check"}],
                },
            ],
        },
    )
    assert problems == [], problems


def test_matcher_schema_flags_uncompilable_regex(tmp_path, monkeypatch):
    # A bad regex matcher is a prime #75071 trigger (silently disables ALL hooks).
    problems = _schema(
        tmp_path,
        monkeypatch,
        {
            "PreToolUse": [
                {"matcher": "Bash(", "hooks": [{"type": "command", "command": "x"}]}
            ],
        },
    )
    assert any("not a valid regex" in p for p in problems), problems


def test_matcher_schema_flags_payloadless_command_hook(tmp_path, monkeypatch):
    problems = _schema(
        tmp_path,
        monkeypatch,
        {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command"}]}
            ],  # no command
        },
    )
    assert any("no command or prompt payload" in p for p in problems), problems


def test_matcher_schema_flags_payloadless_prompt_hook(tmp_path, monkeypatch):
    problems = _schema(
        tmp_path,
        monkeypatch,
        {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "prompt"}]}
            ],  # no prompt
        },
    )
    assert any("no command or prompt payload" in p for p in problems), problems


def test_matcher_schema_optional_matcher_ok(tmp_path, monkeypatch):
    # matcher is optional (some events match all inputs); absence must NOT be flagged.
    problems = _schema(
        tmp_path,
        monkeypatch,
        {
            "SessionStart": [{"hooks": [{"type": "command", "command": "x"}]}],
        },
    )
    assert problems == [], problems


def test_matcher_schema_implicit_type_ok(tmp_path, monkeypatch):
    # A hook with a command but no explicit `type` is valid (type is implicit) —
    # matches the codebase's own fixtures; over-rejecting it would DoS the check.
    problems = _schema(
        tmp_path,
        monkeypatch,
        {
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [{"command": "x"}]}
            ],  # no type, has command
        },
    )
    assert problems == [], problems


# --- installed plugin hook inventory (A4, #85893) ---------------------------


def _plugin_fixture(
    tmp_path,
    *,
    enabled=False,
    hooks_payload=None,
    raw_hooks=None,
    manifest_payload=None,
    settings_payload=None,
    registry_entry=None,
    project_settings=None,
    local_settings=None,
):
    claude = tmp_path / ".claude"
    plugin = tmp_path / "plugins-src" / "hidden-hooks"
    (plugin / "hooks").mkdir(parents=True, exist_ok=True)
    plugin_id = "hidden-hooks@fixture-marketplace"
    (claude / "plugins").mkdir(parents=True, exist_ok=True)
    settings = (
        {"enabledPlugins": {plugin_id: enabled}, "hooks": {}}
        if settings_payload is None
        else settings_payload
    )
    (claude / "settings.json").write_text(
        json.dumps(settings),
        encoding="utf-8",
    )
    (claude / "plugins" / "installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    plugin_id: [
                        registry_entry
                        or {"scope": "user", "installPath": str(plugin), "version": "1"}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    if raw_hooks is not None:
        (plugin / "hooks" / "hooks.json").write_text(raw_hooks, encoding="utf-8")
    elif hooks_payload is not None:
        (plugin / "hooks" / "hooks.json").write_text(
            json.dumps(hooks_payload), encoding="utf-8"
        )
    if manifest_payload is not None:
        (plugin / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(
            json.dumps(manifest_payload), encoding="utf-8"
        )
    project = tmp_path / "project"
    if project_settings is not None:
        (project / ".claude").mkdir(parents=True, exist_ok=True)
        (project / ".claude" / "settings.json").write_text(
            json.dumps(project_settings), encoding="utf-8"
        )
    if local_settings is not None:
        (project / ".claude").mkdir(parents=True, exist_ok=True)
        (project / ".claude" / "settings.local.json").write_text(
            json.dumps(local_settings), encoding="utf-8"
        )
    return claude, plugin_id, plugin, project


PLUGIN_POST_HOOK = {
    "description": "fixture",
    "hooks": {
        "PostToolUse": [
            {
                "matcher": "Bash",
                "hooks": [{"type": "command", "command": "python fixture.py"}],
            }
        ]
    },
}


def test_disabled_plugin_hooks_are_enumerated_from_install_path(tmp_path):
    claude, plugin_id, plugin, _ = _plugin_fixture(
        tmp_path, enabled=False, hooks_payload=PLUGIN_POST_HOOK
    )

    records, errors = hc.scan_installed_plugin_hooks(claude)

    assert errors == []
    assert len(records) == 1
    assert records[0]["plugin"] == plugin_id
    assert records[0]["state"] == "disabled"
    assert records[0]["enabled"] is False
    assert records[0]["event"] == "PostToolUse"
    assert records[0]["source"] == str(plugin / "hooks" / "hooks.json")


def test_enabled_plugin_hooks_are_still_independently_enumerated(tmp_path):
    claude, plugin_id, _, _ = _plugin_fixture(
        tmp_path, enabled=True, hooks_payload=PLUGIN_POST_HOOK
    )

    records, errors = hc.scan_installed_plugin_hooks(claude)

    assert errors == []
    assert records[0]["plugin"] == plugin_id
    assert records[0]["enabled"] is True


def test_malformed_plugin_hook_metadata_fails_closed(tmp_path):
    claude, _, plugin, _ = _plugin_fixture(
        tmp_path, enabled=False, raw_hooks="{not-json"
    )

    records, errors = hc.scan_installed_plugin_hooks(claude)

    assert records == []
    assert errors
    assert str(plugin / "hooks" / "hooks.json") in errors[0]
    assert "unparseable" in errors[0]


def test_missing_manifest_referenced_hook_file_fails_closed(tmp_path):
    claude, _, _, _ = _plugin_fixture(
        tmp_path,
        enabled=False,
        manifest_payload={"name": "hidden-hooks", "hooks": "./hooks/missing.json"},
    )

    records, errors = hc.scan_installed_plugin_hooks(claude)

    assert records == []
    assert any("missing.json" in error and "missing" in error for error in errors)


def test_missing_user_settings_uses_manifest_default_enabled(tmp_path):
    claude, _, _, _ = _plugin_fixture(
        tmp_path,
        enabled=False,
        hooks_payload=PLUGIN_POST_HOOK,
        manifest_payload={"name": "hidden-hooks", "defaultEnabled": False},
    )
    (claude / "settings.json").unlink()

    records, errors = hc.scan_installed_plugin_hooks(claude)

    assert errors == []
    assert records[0]["state"] == "disabled"


def test_manifest_hook_path_cannot_escape_plugin_install_root(tmp_path):
    outside = tmp_path / "outside-hooks.json"
    outside.write_text(json.dumps(PLUGIN_POST_HOOK), encoding="utf-8")
    claude, _, _, _ = _plugin_fixture(
        tmp_path,
        enabled=False,
        manifest_payload={"name": "hidden-hooks", "hooks": str(outside)},
    )

    records, errors = hc.scan_installed_plugin_hooks(claude)

    assert records == []
    assert any("must start with './'" in error for error in errors)


def test_plugin_hook_mutation_changes_main_from_pass_to_warn(
    tmp_path, monkeypatch, capsys
):
    """Mutation-style proof: adding one disabled hook changes the exit contract."""
    claude = tmp_path / ".claude"
    hooks_dir = claude / "hooks"
    tests_dir = hooks_dir / "test-hooks"
    tests_dir.mkdir(parents=True)
    (claude / "settings.json").write_text(
        json.dumps({"enabledPlugins": {}, "hooks": {}}), encoding="utf-8"
    )
    monkeypatch.setattr(hc, "H", str(claude))
    monkeypatch.setattr(hc, "HOOKS", str(hooks_dir))
    monkeypatch.setattr(hc, "TESTS", str(tests_dir))
    assert hc.main() == 0
    capsys.readouterr()

    _plugin_fixture(tmp_path, enabled=False, hooks_payload=PLUGIN_POST_HOOK)
    rc = hc.main()
    out = capsys.readouterr().out
    assert rc == 1
    assert "DISABLED PLUGIN HOOKS" in out
    assert "PostToolUse" in out
    assert "hooks.json" in out


def test_plugin_metadata_error_is_fatal_exit_2(tmp_path, monkeypatch, capsys):
    claude, _, _, _ = _plugin_fixture(tmp_path, enabled=False, raw_hooks="{bad")
    hooks_dir = claude / "hooks"
    tests_dir = hooks_dir / "test-hooks"
    tests_dir.mkdir(parents=True)
    monkeypatch.setattr(hc, "H", str(claude))
    monkeypatch.setattr(hc, "HOOKS", str(hooks_dir))
    monkeypatch.setattr(hc, "TESTS", str(tests_dir))

    rc = hc.main()
    out = capsys.readouterr().out

    assert rc == 2
    assert out.startswith("PLUGIN HOOK INVENTORY INCOMPLETE")


def test_manifest_hooks_support_string_array_and_inline_object(tmp_path):
    claude, _, plugin, _ = _plugin_fixture(
        tmp_path,
        enabled=True,
        manifest_payload={
            "name": "hidden-hooks",
            "hooks": [
                "./one.json",
                "./two.json",
                PLUGIN_POST_HOOK["hooks"],
            ],
        },
    )
    (plugin / "one.json").write_text(json.dumps(PLUGIN_POST_HOOK), encoding="utf-8")
    second = {
        "PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "x"}]}
        ]
    }
    (plugin / "two.json").write_text(json.dumps(second), encoding="utf-8")

    records, errors = hc.scan_installed_plugin_hooks(claude)

    assert errors == []
    assert len(records) == 3
    assert sorted(record["event"] for record in records) == [
        "PostToolUse",
        "PostToolUse",
        "PreToolUse",
    ]


def test_manifest_hooks_valid_top_level_string_path(tmp_path):
    claude, _, plugin, _ = _plugin_fixture(
        tmp_path,
        enabled=True,
        manifest_payload={"name": "hidden-hooks", "hooks": "./custom.json"},
    )
    (plugin / "custom.json").write_text(json.dumps(PLUGIN_POST_HOOK), encoding="utf-8")

    records, errors = hc.scan_installed_plugin_hooks(claude)

    assert errors == []
    assert len(records) == 1
    assert records[0]["source"] == str((plugin / "custom.json").resolve())


def test_manifest_hook_path_requires_dot_slash_even_when_contained(tmp_path):
    claude, _, plugin, _ = _plugin_fixture(
        tmp_path,
        enabled=True,
        manifest_payload={"name": "hidden-hooks", "hooks": "hooks/hooks.json"},
    )
    (plugin / "hooks" / "hooks.json").write_text(
        json.dumps(PLUGIN_POST_HOOK), encoding="utf-8"
    )

    records, errors = hc.scan_installed_plugin_hooks(claude)

    # A manifest hooks field replaces the conventional default source.
    assert records == []
    assert any("must start with './'" in error for error in errors)


def test_manifest_hooks_field_replaces_default_hooks_file(tmp_path):
    claude, _, plugin, _ = _plugin_fixture(
        tmp_path,
        enabled=True,
        hooks_payload=PLUGIN_POST_HOOK,
        manifest_payload={
            "name": "hidden-hooks",
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "x"}],
                    }
                ]
            },
        },
    )

    records, errors = hc.scan_installed_plugin_hooks(claude)

    assert errors == []
    assert len(records) == 1
    assert records[0]["event"] == "PreToolUse"
    assert records[0]["source"].endswith("plugin.json#hooks[0]")
    assert str(plugin / "hooks" / "hooks.json") not in records[0]["source"]


def test_manifest_hook_symlink_escape_fails_closed(tmp_path):
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(PLUGIN_POST_HOOK), encoding="utf-8")
    claude, _, plugin, _ = _plugin_fixture(
        tmp_path,
        enabled=True,
        manifest_payload={"name": "hidden-hooks", "hooks": "./linked.json"},
    )
    (plugin / "linked.json").symlink_to(outside)

    records, errors = hc.scan_installed_plugin_hooks(claude)

    assert records == []
    assert any("outside plugin root" in error for error in errors)


def test_enabled_plugins_local_then_project_then_user_precedence(tmp_path):
    claude, plugin_id, _, project = _plugin_fixture(
        tmp_path,
        enabled=False,
        hooks_payload=PLUGIN_POST_HOOK,
        project_settings={"enabledPlugins": {"hidden-hooks@fixture-marketplace": True}},
        local_settings={"enabledPlugins": {"hidden-hooks@fixture-marketplace": False}},
    )

    records, errors = hc.scan_installed_plugin_hooks(claude, project_dir=project)

    assert errors == []
    assert records[0]["plugin"] == plugin_id
    assert records[0]["state"] == "disabled"
    assert "settings.local.json" in records[0]["state_source"]


def test_project_setting_overrides_user_when_local_omits_plugin(tmp_path):
    claude, _, _, project = _plugin_fixture(
        tmp_path,
        enabled=False,
        hooks_payload=PLUGIN_POST_HOOK,
        project_settings={"enabledPlugins": {"hidden-hooks@fixture-marketplace": True}},
        local_settings={"enabledPlugins": {}},
    )

    records, errors = hc.scan_installed_plugin_hooks(claude, project_dir=project)

    assert errors == []
    assert records[0]["state"] == "enabled"
    assert "settings.json" in records[0]["state_source"]


def test_project_scoped_registry_path_beats_unrelated_current_project(tmp_path):
    project = tmp_path / "project"
    current = tmp_path / "unrelated-current"
    (current / ".claude").mkdir(parents=True)
    (current / ".claude" / "settings.local.json").write_text(
        json.dumps({"enabledPlugins": {"hidden-hooks@fixture-marketplace": False}}),
        encoding="utf-8",
    )
    claude, _, plugin, project = _plugin_fixture(
        tmp_path,
        enabled=False,
        hooks_payload=PLUGIN_POST_HOOK,
        registry_entry={
            "scope": "project",
            "projectPath": str(project),
            "installPath": str(tmp_path / "plugins-src" / "hidden-hooks"),
            "version": "1",
        },
        project_settings={"enabledPlugins": {"hidden-hooks@fixture-marketplace": True}},
    )

    records, errors = hc.scan_installed_plugin_hooks(claude, project_dir=current)

    assert errors == []
    assert records[0]["state"] == "enabled"
    assert str(project / ".claude" / "settings.json") in records[0]["state_source"]
    assert records[0]["source"] == str(plugin / "hooks" / "hooks.json")


def test_default_enabled_false_is_fallback_when_no_scope_sets_state(tmp_path):
    claude, _, _, _ = _plugin_fixture(
        tmp_path,
        hooks_payload=PLUGIN_POST_HOOK,
        settings_payload={"enabledPlugins": {}},
        manifest_payload={"name": "hidden-hooks", "defaultEnabled": False},
    )

    records, errors = hc.scan_installed_plugin_hooks(claude)

    assert errors == []
    assert records[0]["state"] == "disabled"
    assert records[0]["state_source"].endswith("#defaultEnabled")


def test_missing_default_enabled_uses_documented_true_default(tmp_path):
    claude, _, _, _ = _plugin_fixture(
        tmp_path,
        hooks_payload=PLUGIN_POST_HOOK,
        settings_payload={"enabledPlugins": {}},
        manifest_payload={"name": "hidden-hooks"},
    )

    records, errors = hc.scan_installed_plugin_hooks(claude)

    assert errors == []
    assert records[0]["state"] == "enabled"
    assert records[0]["state_source"].endswith("#defaultEnabled(default=true)")


def test_marketplace_default_enabled_overrides_manifest_default(tmp_path):
    claude, _, _, _ = _plugin_fixture(
        tmp_path,
        hooks_payload=PLUGIN_POST_HOOK,
        settings_payload={"enabledPlugins": {}},
        manifest_payload={"name": "hidden-hooks", "defaultEnabled": False},
    )
    marketplace = (
        claude / "plugins" / "marketplaces" / "fixture-marketplace" / ".claude-plugin"
    )
    marketplace.mkdir(parents=True)
    (marketplace / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "fixture-marketplace",
                "plugins": [{"name": "hidden-hooks", "defaultEnabled": True}],
            }
        ),
        encoding="utf-8",
    )

    records, errors = hc.scan_installed_plugin_hooks(claude)

    assert errors == []
    assert records[0]["state"] == "enabled"
    assert "marketplace.json" in records[0]["state_source"]


def test_project_scoped_install_without_project_path_is_unknown_not_disabled(
    tmp_path, monkeypatch, capsys
):
    claude, _, _, _ = _plugin_fixture(
        tmp_path,
        hooks_payload=PLUGIN_POST_HOOK,
        settings_payload={"enabledPlugins": {}},
        registry_entry={
            "scope": "project",
            "installPath": str(tmp_path / "plugins-src" / "hidden-hooks"),
            "version": "1",
        },
    )
    records, errors = hc.scan_installed_plugin_hooks(claude)
    assert errors == []
    assert records[0]["state"] == "unknown"
    assert records[0]["enabled"] is None

    hooks_dir = claude / "hooks"
    tests_dir = hooks_dir / "test-hooks"
    tests_dir.mkdir(parents=True)
    monkeypatch.setattr(hc, "H", str(claude))
    monkeypatch.setattr(hc, "HOOKS", str(hooks_dir))
    monkeypatch.setattr(hc, "TESTS", str(tests_dir))
    monkeypatch.setattr(hc, "PROJECT_CWD", None)
    assert hc.main() == 1
    assert "UNKNOWN PLUGIN HOOK STATE" in capsys.readouterr().out


def test_malformed_default_enabled_fails_closed(tmp_path):
    claude, _, _, _ = _plugin_fixture(
        tmp_path,
        hooks_payload=PLUGIN_POST_HOOK,
        settings_payload={"enabledPlugins": {}},
        manifest_payload={"name": "hidden-hooks", "defaultEnabled": "no"},
    )

    records, errors = hc.scan_installed_plugin_hooks(claude)

    assert records
    assert any("defaultEnabled" in error and "boolean" in error for error in errors)
