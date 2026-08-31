"""Unit tests for healthcheck/references/_check_config.py (Check 2).

Pins the JSON-parse contract: all parseable → PASS(0); a malformed config →
FAIL(1) naming the file. Also pins the exact MCP/skill collision
guard: a collision can silently drop the MCP server from Claude Code's tool
inventory, so it is a hard config failure. Plugin components use their documented
namespaces and therefore do not collide with bare standalone names.
"""

import importlib.util
import json
import time
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hc_check_config",
    Path(__file__).resolve().parent.parent / "references" / "_check_config.py",
)
assert _SPEC and _SPEC.loader
hc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hc)


def _wire(tmp_path, monkeypatch, files):
    claude = tmp_path / ".claude"
    for rel, content in files.items():
        fp = claude / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
    monkeypatch.setattr(hc, "CLAUDE_DIR", claude)
    monkeypatch.setattr(hc, "HOME", tmp_path)  # no ~/.mcp.json or ~/.claude.json here
    monkeypatch.setattr(hc, "PROJ", "")
    monkeypatch.setattr(hc, "PLUGINS_DIR", claude / "plugins")
    monkeypatch.setattr(hc, "PROJECT_CWD", tmp_path)
    monkeypatch.setattr(hc, "MANAGED_MCP_PATH", tmp_path / "managed-mcp.json")
    return claude


def test_all_valid_passes(tmp_path, monkeypatch):
    _wire(
        tmp_path,
        monkeypatch,
        {
            "settings.json": "{}",
            "hooks/skill-rules.json": '{"rules": [], "skip_patterns": []}',
        },
    )
    status, msg = hc.check_config()
    assert status == "PASS"
    assert "2 files valid" in msg


def test_malformed_json_fails_with_filename(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, {"settings.json": "{not valid json"})
    status, msg = hc.check_config()
    assert status == "FAIL"
    assert "settings.json" in msg


def test_main_exit_codes(tmp_path, monkeypatch, capsys):
    _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    assert hc.main() == 0
    assert "Config: PASS" in capsys.readouterr().out
    _wire(tmp_path, monkeypatch, {"settings.json": "{bad"})
    assert hc.main() == 1


def _skill(root: Path, folder: str, name: str) -> Path:
    skill = root / "skills" / folder / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        f"---\nname: {name}\ndescription: fixture\n---\n\n## Examples\n",
        encoding="utf-8",
    )
    return skill


def test_mcp_skill_exact_collision_is_hard_failure(tmp_path, monkeypatch):
    claude = _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    _skill(claude, "alpha-mcp", "alpha-mcp")
    (tmp_path / ".claude.json").write_text(
        json.dumps({"mcpServers": {"alpha-mcp": {"type": "http"}}}),
        encoding="utf-8",
    )

    status, msg = hc.check_config()

    assert status == "FAIL"
    assert "MCP/skill name collision" in msg
    assert "alpha-mcp" in msg.casefold()
    assert "rename the MCP server or skill" in msg


def test_case_and_unicode_variants_do_not_overreach_runtime_evidence(
    tmp_path, monkeypatch
):
    claude = _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    _skill(claude, "Alpha-MCP", "display-only")
    _skill(claude, "café", "display-only")
    (tmp_path / ".claude.json").write_text(
        json.dumps({"mcpServers": {"alpha-mcp": {}, "cafe\u0301": {}}}),
        encoding="utf-8",
    )

    status, msg = hc.check_config()

    assert status == "PASS", msg


def test_reserved_synced_directory_is_ignored_in_any_capitalization(
    tmp_path, monkeypatch
):
    claude = _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    _skill(claude, "SyNcEd", "display-only")
    (tmp_path / ".claude.json").write_text(
        json.dumps({"mcpServers": {"SyNcEd": {}}}), encoding="utf-8"
    )

    status, msg = hc.check_config()

    assert status == "PASS", msg


def test_frontmatter_name_does_not_replace_standalone_directory_identity(
    tmp_path, monkeypatch
):
    claude = _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    _skill(claude, "safe-directory", "colliding-display-label")
    (tmp_path / ".claude.json").write_text(
        json.dumps({"mcpServers": {"colliding-display-label": {}}}),
        encoding="utf-8",
    )

    status, msg = hc.check_config()

    assert status == "PASS", msg


def test_plugin_skill_namespace_does_not_collide_with_bare_mcp(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    plugin = tmp_path / "plugin-alpha"
    _skill(plugin, "gamma", "gamma")
    plugins = tmp_path / ".claude" / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    (plugins / "installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "alpha@fixture": [
                        {"scope": "user", "installPath": str(plugin), "version": "1"}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / ".claude.json").write_text(
        json.dumps({"mcpServers": {"gamma": {"type": "stdio"}}}),
        encoding="utf-8",
    )

    status, msg = hc.check_config()

    assert status == "PASS", msg


def test_plugin_mcp_namespace_does_not_collide_with_bare_skill(tmp_path, monkeypatch):
    claude = _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    _skill(claude, "gamma", "gamma")
    plugin = tmp_path / "plugin-alpha"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "alpha", "mcpServers": {"gamma": {}}}),
        encoding="utf-8",
    )
    plugins = claude / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    (plugins / "installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "alpha@fixture": [
                        {"scope": "user", "installPath": str(plugin), "version": "1"}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    status, msg = hc.check_config()

    assert status == "PASS", msg


def test_plugin_components_are_informational_not_hard_collision_inputs(
    tmp_path, monkeypatch
):
    claude = _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    _skill(claude, "plugin:alpha:server", "display")
    plugin = tmp_path / "plugin-alpha"
    _skill(plugin, "skill", "server")
    _install_plugin(
        claude,
        plugin,
        {"name": "alpha", "mcpServers": {"server": {}}},
    )
    (tmp_path / ".claude.json").write_text(
        json.dumps({"mcpServers": {"alpha:server": {}}}), encoding="utf-8"
    )

    status, msg = hc.check_config()

    assert status == "PASS", msg


def test_unrelated_project_scopes_do_not_false_collide(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    _skill(project_b / ".claude", "shared-name", "shared-name")
    (tmp_path / ".claude.json").write_text(
        json.dumps(
            {
                "projects": {
                    str(project_a): {"mcpServers": {"shared-name": {}}},
                    str(project_b): {"mcpServers": {}},
                }
            }
        ),
        encoding="utf-8",
    )

    status, msg = hc.check_config()

    assert status == "PASS", msg


def test_collision_mutation_control_then_injected_name(tmp_path, monkeypatch):
    """Mutation-style proof: changing only the MCP name kills the clean result."""
    claude = _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    _skill(claude, "delta", "delta")
    state = tmp_path / ".claude.json"
    state.write_text(json.dumps({"mcpServers": {"epsilon": {}}}), encoding="utf-8")
    assert hc.check_config()[0] == "PASS"

    state.write_text(json.dumps({"mcpServers": {"delta": {}}}), encoding="utf-8")
    status, msg = hc.check_config()
    assert status == "FAIL"
    assert "MCP/skill name collision" in msg


def test_user_command_file_stem_participates_in_exact_collision_guard(
    tmp_path, monkeypatch
):
    claude = _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    (claude / "commands").mkdir()
    (claude / "commands" / "command-server.md").write_text(
        "---\nname: display-only\n---\n", encoding="utf-8"
    )
    (tmp_path / ".claude.json").write_text(
        json.dumps({"mcpServers": {"command-server": {}}}), encoding="utf-8"
    )

    status, msg = hc.check_config()

    assert status == "FAIL"
    assert "command-server" in msg


def test_project_command_file_stem_loads_from_parent_directory(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    cwd = repo / "packages" / "api"
    cwd.mkdir(parents=True)
    commands = repo / "packages" / ".claude" / "commands"
    commands.mkdir(parents=True)
    (commands / "parent-command.md").write_text("fixture\n", encoding="utf-8")
    (repo / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"parent-command": {}}}), encoding="utf-8"
    )
    monkeypatch.setattr(hc, "PROJECT_CWD", cwd)

    collisions, errors, _, _ = hc.check_mcp_skill_collisions()

    assert errors == []
    assert [row[0] for row in collisions] == ["parent-command"]


def _project_skill(project: Path, rel: str, name: str) -> Path:
    skill = project / rel / ".claude" / "skills" / name / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("---\ndescription: fixture\n---\n", encoding="utf-8")
    return skill


def test_project_skills_load_from_cwd_and_each_parent_to_repo_root(
    tmp_path, monkeypatch
):
    _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    cwd = repo / "packages" / "api"
    cwd.mkdir(parents=True)
    _project_skill(repo, "", "root-server")
    _project_skill(repo, "packages", "parent-server")
    _project_skill(repo, "packages/api", "cwd-server")
    (repo / ".mcp.json").write_text(
        json.dumps(
            {"mcpServers": {"root-server": {}, "parent-server": {}, "cwd-server": {}}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(hc, "PROJECT_CWD", cwd)

    collisions, errors, _, _ = hc.check_mcp_skill_collisions()

    assert errors == []
    assert {row[0] for row in collisions} == {
        "cwd-server",
        "parent-server",
        "root-server",
    }


def test_nested_project_skills_are_discovered_on_demand_inventory(
    tmp_path, monkeypatch
):
    _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "packages" / "web").mkdir(parents=True)
    _project_skill(repo, "packages/web", "nested-server")
    (repo / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"nested-server": {}}}), encoding="utf-8"
    )
    monkeypatch.setattr(hc, "PROJECT_CWD", repo)

    collisions, errors, _, _ = hc.check_mcp_skill_collisions()

    assert errors == []
    assert [row[0] for row in collisions] == ["nested-server"]


def test_historical_non_repo_home_project_scan_is_bounded_and_nonrecursive(
    tmp_path, monkeypatch
):
    _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    historical_home = tmp_path / "historical-home"
    _project_skill(historical_home, "", "direct-server")
    _project_skill(historical_home, "Documents/large-tree", "nested-server")
    (tmp_path / ".claude.json").write_text(
        json.dumps(
            {
                "projects": {
                    str(historical_home): {
                        "mcpServers": {
                            "direct-server": {},
                            "nested-server": {},
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    walked = []
    real_nested = hc._nested_skill_dirs

    def guarded_nested(path):
        walked.append(path)
        if path == historical_home:
            raise AssertionError(
                "historical non-repository path was recursively walked"
            )
        yield from real_nested(path)

    monkeypatch.setattr(hc, "_nested_skill_dirs", guarded_nested)
    started = time.monotonic()

    collisions, errors, _, _ = hc.check_mcp_skill_collisions()

    assert time.monotonic() - started < 1.0
    assert errors == []
    assert walked == []
    assert [row[0] for row in collisions] == ["direct-server"]


def test_nested_discovery_prunes_dependency_and_build_trees(tmp_path, monkeypatch):
    _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    _project_skill(repo, "node_modules/pkg", "dependency-server")
    _project_skill(repo, "target/generated", "build-server")
    _project_skill(repo, "packages/real", "real-server")
    (repo / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "dependency-server": {},
                    "build-server": {},
                    "real-server": {},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(hc, "PROJECT_CWD", repo)

    collisions, errors, _, _ = hc.check_mcp_skill_collisions()

    assert errors == []
    assert [row[0] for row in collisions] == ["real-server"]


def _install_plugin(claude: Path, plugin: Path, manifest: dict | None = None):
    if manifest is not None:
        (plugin / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
    (claude / "plugins").mkdir(parents=True, exist_ok=True)
    (claude / "plugins" / "installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "inventory@fixture": [
                        {"scope": "user", "installPath": str(plugin), "version": "1"}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )


def test_plugin_skill_default_custom_string_array_and_root_shapes(
    tmp_path, monkeypatch
):
    claude = _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    plugin = tmp_path / "plugin"
    _skill(plugin, "default-skill", "default-skill")
    _skill(plugin / "custom-one", "one", "one")
    _skill(plugin / "custom-two", "two", "two")
    (plugin / "root-skill").mkdir(parents=True)
    (plugin / "root-skill" / "SKILL.md").write_text(
        "---\nname: root-one\ndescription: fixture\n---\n", encoding="utf-8"
    )
    _install_plugin(
        claude,
        plugin,
        {
            "name": "inventory",
            "skills": ["./custom-one/skills", "./custom-two/skills", "./root-skill"],
        },
    )

    collisions, errors, _, skill_count = hc.check_mcp_skill_collisions()

    assert collisions == []
    assert errors == []
    # Custom skill directories add to the documented default skills/ scan.
    assert skill_count == 4


def test_plugin_skill_custom_top_level_string_shape(tmp_path, monkeypatch):
    claude = _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    plugin = tmp_path / "plugin"
    _skill(plugin / "custom", "one", "one")
    _install_plugin(
        claude,
        plugin,
        {"name": "inventory", "skills": "./custom/skills"},
    )

    collisions, errors, _, skill_count = hc.check_mcp_skill_collisions()

    assert collisions == []
    assert errors == []
    assert skill_count == 1


def test_single_skill_plugin_root_is_discovered_without_manifest_field(
    tmp_path, monkeypatch
):
    claude = _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / "SKILL.md").write_text(
        "---\nname: root-skill\ndescription: fixture\n---\n", encoding="utf-8"
    )
    _install_plugin(claude, plugin, {"name": "inventory"})

    _, errors, _, skill_count = hc.check_mcp_skill_collisions()

    assert errors == []
    assert skill_count == 1


def test_plugin_mcp_default_string_array_and_inline_object_shapes(
    tmp_path, monkeypatch
):
    claude = _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"default": {}}}), encoding="utf-8"
    )
    (plugin / "one.json").write_text(
        json.dumps({"mcpServers": {"one": {}}}), encoding="utf-8"
    )
    (plugin / "two.json").write_text(json.dumps({"two": {}}), encoding="utf-8")
    _install_plugin(
        claude,
        plugin,
        {
            "name": "inventory",
            "mcpServers": ["./one.json", "./two.json", {"inline": {}}],
        },
    )

    collisions, errors, mcp_count, _ = hc.check_mcp_skill_collisions()

    assert collisions == []
    assert errors == []
    assert mcp_count == 4


def test_managed_mcp_is_exclusive_and_participates_in_collision_guard(
    tmp_path, monkeypatch
):
    claude = _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    _skill(claude, "graphify", "display-only")
    (tmp_path / "managed-mcp.json").write_text(
        json.dumps({"mcpServers": {"graphify": {}}}), encoding="utf-8"
    )

    status, msg = hc.check_config()

    assert status == "FAIL"
    assert "graphify" in msg
    assert "managed-mcp.json" in msg


def test_managed_mcp_suppresses_stale_user_project_and_plugin_servers(
    tmp_path, monkeypatch
):
    claude = _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    _skill(claude, "graphify", "display-only")
    (tmp_path / ".claude.json").write_text(
        json.dumps({"mcpServers": {"graphify": {}}}), encoding="utf-8"
    )
    (tmp_path / "managed-mcp.json").write_text(
        json.dumps({"mcpServers": {"managed-other": {}}}), encoding="utf-8"
    )

    status, msg = hc.check_config()

    assert status == "PASS", msg
    assert "1 MCP names" in msg


def test_plugin_component_paths_must_be_relative_dot_slash_and_contained(
    tmp_path, monkeypatch
):
    claude = _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    _install_plugin(
        claude,
        plugin,
        {"name": "inventory", "skills": ["custom/skills", "./../escape"]},
    )

    status, msg = hc.check_config()

    assert status == "FAIL"
    assert "must start with './'" in msg
    assert "outside plugin root" in msg


def test_plugin_component_malformed_array_member_fails_closed(tmp_path, monkeypatch):
    claude = _wire(tmp_path, monkeypatch, {"settings.json": "{}"})
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    _install_plugin(
        claude,
        plugin,
        {"name": "inventory", "mcpServers": ["./valid.json", 7]},
    )
    (plugin / "valid.json").write_text("{}", encoding="utf-8")

    status, msg = hc.check_config()

    assert status == "FAIL"
    assert "string or object" in msg
