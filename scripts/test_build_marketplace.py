"""Acceptance tests for the generated Claude Code plugin marketplace."""

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "scripts" / "build-marketplace.py"
SAFETY_NET = ROOT / "marketplace" / "safety-net"
KNOWLEDGE_OPS = ROOT / "marketplace" / "knowledge-ops"


def _load_builder():
    spec = importlib.util.spec_from_file_location("build_marketplace", BUILD)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _build_marketplace() -> str:
    completed = subprocess.run(
        [sys.executable, str(BUILD)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_safety_net_registers_bash_security_guard() -> None:
    """A clean marketplace build must activate its primary security guard."""
    _build_marketplace()

    hook_config = json.loads(
        (SAFETY_NET / "hooks" / "hooks.json").read_text(encoding="utf-8")
    )
    pre_tool_use = hook_config["hooks"]["PreToolUse"]
    bash_group = next(group for group in pre_tool_use if group["matcher"] == "Bash")
    handler = bash_group["hooks"][0]

    assert handler == {
        "type": "command",
        "command": "bash",
        "args": [
            "${CLAUDE_PLUGIN_ROOT}/hooks/run-hook",
            "bash-security-guard.py",
        ],
        "timeout": 30,
    }


def test_generated_plugins_include_author_metadata() -> None:
    """Strict Claude plugin validation requires attributable manifests."""
    _build_marketplace()

    manifest = json.loads(
        (SAFETY_NET / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )

    assert manifest["author"] == {
        "name": "the maintainers",
        "url": "https://github.com/example-org",
    }


def test_marketplace_is_owned_by_canonical_organization() -> None:
    """Generated catalog metadata must not point consumers at the old owner."""
    _build_marketplace()

    catalog = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )

    assert catalog["owner"] == {
        "name": "the maintainers",
        "url": "https://github.com/example-org",
    }


def test_build_prints_canonical_install_command() -> None:
    """The builder's copy/paste command must install from the org repository."""
    stdout = _build_marketplace()

    assert (
        "/plugin marketplace add brandyn-s/claude-harness"
        in [line.strip() for line in stdout.splitlines()]
    )


def test_knowledge_ops_ships_retro_recovery_runtime() -> None:
    """Published retro must include both recovery skills and their executable."""
    _build_marketplace()

    for skill_name in ("mega-distill", "mega-capture"):
        packaged_skill = KNOWLEDGE_OPS / "skills" / skill_name / "SKILL.md"
        assert packaged_skill.is_file()
        body = packaged_skill.read_text(encoding="utf-8")
        assert f"name: {skill_name}" in body
        assert "$CLAUDE_PLUGIN_ROOT/skills/mega-distill" in body
        assert "~/.claude/skills/mega-distill" not in body

    executable = (
        KNOWLEDGE_OPS
        / "skills"
        / "mega-distill"
        / "scripts"
        / "transcript_condense.py"
    )
    assert executable.is_file()
    compile(executable.read_text(encoding="utf-8"), str(executable), "exec")

    completed = subprocess.run(
        [
            sys.executable,
            str(executable),
            "--help",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_shared_asset_discovery_follows_policy_overlay_links_without_allowlist(
    tmp_path, monkeypatch
) -> None:
    """New model overlays ship when the policy references them."""
    builder = _load_builder()
    source = tmp_path / "source"
    (source / "skills" / "example").mkdir(parents=True)
    (source / "skills" / "example" / "SKILL.md").write_text(
        "Resolve `../_shared/model-runtime-policy.md`.\n", encoding="utf-8"
    )
    overlays = source / "skills" / "_shared" / "model-overlays"
    overlays.mkdir(parents=True)
    names = ("fable-5.md", "mythos-5.md", "opus-5.md", "sonnet-5.md")
    (source / "skills" / "_shared" / "model-runtime-policy.md").write_text(
        "\n".join(f"- `model-overlays/{name}`" for name in names) + "\n",
        encoding="utf-8",
    )
    for name in names:
        (overlays / name).write_text(f"{name}\n", encoding="utf-8")

    monkeypatch.setattr(builder, "CLAUDE_DIR", source)
    discovered = builder._discover_shared_assets(["example"])

    assert {
        path.relative_to(source / "skills" / "_shared").as_posix()
        for path in discovered
    } == {
        "model-runtime-policy.md",
        *(f"model-overlays/{name}" for name in names),
    }


def test_temp_plugin_closes_skill_shared_and_helper_dependencies(
    tmp_path, monkeypatch
) -> None:
    """A root skill's complete composed runtime must fit in one plugin."""
    builder = _load_builder()
    source = tmp_path / "source"
    marketplace = tmp_path / "marketplace"

    def write_skill(name: str, dependencies: list[str], body: str) -> Path:
        skill = source / "skills" / name
        skill.mkdir(parents=True)
        requires = (
            "requires_skills: []"
            if not dependencies
            else "requires_skills:\n" + "\n".join(
                f"  - {dependency}" for dependency in dependencies
            )
        )
        (skill / "manifest.yaml").write_text(
            f"id: {name}\n{requires}\n", encoding="utf-8"
        )
        (skill / "SKILL.md").write_text(body, encoding="utf-8")
        return skill

    root = write_skill(
        "root",
        ["middle"],
        "Read `../_shared/change-validation.md`.\n"
        "Run `python3 ~/.claude/skills/leaf/scripts/tool.py`.\n"
        "Run `python3 ~/.claude/bin/entry.py`.\n",
    )
    write_skill("middle", ["leaf"], "Read `../_shared/oracle/`.\n")
    leaf = write_skill("leaf", [], "Leaf.\n")
    (leaf / "scripts").mkdir()
    (leaf / "scripts" / "tool.py").write_text("print('leaf')\n", encoding="utf-8")
    shared = source / "skills" / "_shared"
    (shared / "oracle").mkdir(parents=True)
    (shared / "change-validation.md").write_text("method\n", encoding="utf-8")
    (shared / "oracle" / "__init__.py").write_text("VALUE = 7\n", encoding="utf-8")
    (source / "bin").mkdir()
    (source / "bin" / "entry.py").write_text(
        "import sibling\nprint(sibling.VALUE)\n", encoding="utf-8"
    )
    (source / "bin" / "sibling.py").write_text("VALUE = 7\n", encoding="utf-8")
    (source / "scripts").mkdir()

    monkeypatch.setattr(builder, "CLAUDE_DIR", source)
    monkeypatch.setattr(builder, "MARKETPLACE_DIR", marketplace)
    plugin_def = {
        "name": "fixture",
        "description": "fixture",
        "version": "1.0.0",
        "files": [(str(root.relative_to(source) / "SKILL.md"), "skills/root/SKILL.md")],
    }

    builder.build_plugin(plugin_def)
    plugin = marketplace / "fixture"
    lock = json.loads(
        (plugin / ".claude-plugin" / "dependency-lock.json").read_text(
            encoding="utf-8"
        )
    )
    assert lock["packaged_skills"] == ["root", "middle", "leaf"]
    assert (plugin / "skills" / "leaf" / "scripts" / "tool.py").is_file()
    assert (plugin / "skills" / "_shared" / "change-validation.md").is_file()
    assert (plugin / "skills" / "_shared" / "oracle" / "__init__.py").is_file()
    assert (plugin / "bin" / "entry.py").is_file()
    assert (plugin / "bin" / "sibling.py").is_file()
    cached = (plugin / "skills" / "root" / "SKILL.md").read_text(encoding="utf-8")
    assert "~/.claude/skills/" not in cached
    assert "${CLAUDE_PLUGIN_ROOT}/skills/leaf/scripts/tool.py" in cached

    completed = subprocess.run(
        [sys.executable, str(plugin / "bin" / "entry.py")],
        cwd=plugin,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(plugin)},
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "7"


def test_packaged_search_path_guard_blocks_without_python_rewrite_corruption(
    tmp_path, monkeypatch
) -> None:
    """A portable-path rewrite must not turn hook prose into an f-string name."""
    builder = _load_builder()
    marketplace = tmp_path / "marketplace"
    monkeypatch.setattr(builder, "MARKETPLACE_DIR", marketplace)
    safety = next(plugin for plugin in builder.PLUGINS if plugin["name"] == "safety-net")

    builder.build_plugin(safety)
    plugin = marketplace / "safety-net"
    payload = json.dumps(
        {
            "tool_name": "Glob",
            "tool_input": {"pattern": "**/*.py", "path": str(Path.home())},
        }
    )
    completed = subprocess.run(
        [sys.executable, str(plugin / "hooks" / "search-path-guard.py")],
        cwd=plugin,
        input=payload,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2, completed.stderr
    assert "NameError" not in completed.stderr
    assert '"decision": "block"' in completed.stdout


def test_dependency_closure_fails_closed_on_unknown_or_inert_skill(
    tmp_path, monkeypatch
) -> None:
    builder = _load_builder()
    source = tmp_path / "source"
    root = source / "skills" / "root"
    root.mkdir(parents=True)
    (root / "manifest.yaml").write_text(
        "id: root\nrequires_skills:\n  - missing\n", encoding="utf-8"
    )
    (root / "SKILL.md").write_text("root\n", encoding="utf-8")
    monkeypatch.setattr(builder, "CLAUDE_DIR", source)

    with pytest.raises(ValueError, match="unknown required skill"):
        builder._skill_dependency_closure(["root"])

    (root / "manifest.yaml").write_text(
        "id: root\nrequires_skills:\n  - sca-review\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="intentionally non-packageable"):
        builder._skill_dependency_closure(["root"])


def test_manifest_parser_rejects_duplicate_dependency_keys(
    tmp_path, monkeypatch
) -> None:
    builder = _load_builder()
    source = tmp_path / "source"
    skill = source / "skills" / "root"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("root\n", encoding="utf-8")
    (skill / "manifest.yaml").write_text(
        "id: root\nrequires_skills: []\nrequires_skills:\n  - hidden\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(builder, "CLAUDE_DIR", source)

    with pytest.raises(ValueError, match="duplicate requires_skills"):
        builder._read_requires_skills("root")


def test_build_preflight_preserves_previous_plugin_on_missing_source(
    tmp_path, monkeypatch
) -> None:
    builder = _load_builder()
    source = tmp_path / "source"
    marketplace = tmp_path / "marketplace"
    previous = marketplace / "fixture"
    previous.mkdir(parents=True)
    sentinel = previous / "last-known-good.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    monkeypatch.setattr(builder, "CLAUDE_DIR", source)
    monkeypatch.setattr(builder, "MARKETPLACE_DIR", marketplace)
    plugin_def = {
        "name": "fixture",
        "description": "fixture",
        "version": "1.0.0",
        "files": [("hooks/missing.py", "hooks/missing.py")],
    }

    with pytest.raises(FileNotFoundError, match="explicit plugin source"):
        builder.build_plugin(plugin_def)

    assert sentinel.read_text(encoding="utf-8") == "keep\n"


@pytest.mark.parametrize(
    ("source_path", "destination_path"),
    [
        ("../outside.txt", "hooks/tool.txt"),
        ("hooks/tool.txt", "../escaped.txt"),
    ],
)
def test_build_rejects_explicit_path_traversal_before_writing(
    tmp_path, monkeypatch, source_path, destination_path
) -> None:
    builder = _load_builder()
    source = tmp_path / "source"
    marketplace = tmp_path / "marketplace"
    (source / "hooks").mkdir(parents=True)
    (source / "hooks" / "tool.txt").write_text("tool\n", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("outside\n", encoding="utf-8")
    monkeypatch.setattr(builder, "CLAUDE_DIR", source)
    monkeypatch.setattr(builder, "MARKETPLACE_DIR", marketplace)
    plugin_def = {
        "name": "fixture",
        "description": "fixture",
        "version": "1.0.0",
        "files": [(source_path, destination_path)],
    }

    with pytest.raises(ValueError, match="relative path"):
        builder.build_plugin(plugin_def)

    assert not (marketplace / "escaped.txt").exists()


def test_build_rejects_symlink_escape_and_preserves_previous_plugin(
    tmp_path, monkeypatch
) -> None:
    builder = _load_builder()
    source = tmp_path / "source"
    marketplace = tmp_path / "marketplace"
    skill = source / "skills" / "root"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("root\n", encoding="utf-8")
    (skill / "manifest.yaml").write_text(
        "id: root\nrequires_skills: []\n", encoding="utf-8"
    )
    secret = tmp_path / "outside-secret.txt"
    secret.write_text("do not package\n", encoding="utf-8")
    (skill / "leak.txt").symlink_to(secret)
    previous = marketplace / "fixture"
    previous.mkdir(parents=True)
    sentinel = previous / "last-known-good.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    monkeypatch.setattr(builder, "CLAUDE_DIR", source)
    monkeypatch.setattr(builder, "MARKETPLACE_DIR", marketplace)
    plugin_def = {
        "name": "fixture",
        "description": "fixture",
        "version": "1.0.0",
        "files": [("skills/root/SKILL.md", "skills/root/SKILL.md")],
    }

    with pytest.raises(ValueError, match="symlink"):
        builder.build_plugin(plugin_def)

    assert sentinel.read_text(encoding="utf-8") == "keep\n"


def test_build_rejects_existing_cross_skill_target_that_was_not_packaged(
    tmp_path, monkeypatch
) -> None:
    builder = _load_builder()
    source = tmp_path / "source"
    marketplace = tmp_path / "marketplace"
    root = source / "skills" / "root"
    dependency = source / "skills" / "dependency"
    root.mkdir(parents=True)
    (dependency / "references").mkdir(parents=True)
    (root / "manifest.yaml").write_text(
        "id: root\nrequires_skills: []\n", encoding="utf-8"
    )
    (root / "SKILL.md").write_text(
        "Read `~/.claude/skills/dependency/references/contract.md`.\n",
        encoding="utf-8",
    )
    (dependency / "manifest.yaml").write_text(
        "id: dependency\nrequires_skills: []\n", encoding="utf-8"
    )
    (dependency / "SKILL.md").write_text("dependency\n", encoding="utf-8")
    (dependency / "references" / "contract.md").write_text(
        "contract\n", encoding="utf-8"
    )
    monkeypatch.setattr(builder, "CLAUDE_DIR", source)
    monkeypatch.setattr(builder, "MARKETPLACE_DIR", marketplace)
    plugin_def = {
        "name": "fixture",
        "description": "fixture",
        "version": "1.0.0",
        "files": [("skills/root/SKILL.md", "skills/root/SKILL.md")],
    }

    with pytest.raises(ValueError, match="missing packaged skill target"):
        builder.build_plugin(plugin_def)


def test_all_active_model_policy_references_are_portable() -> None:
    """Canonical and cached use resolve the same relative shared contract."""
    old_refs = []
    nonportable_refs = []
    for skill_md in sorted((ROOT / "skills").glob("*/SKILL.md")):
        body = skill_md.read_text(encoding="utf-8")
        if "model-runtime-policy.md" not in body:
            continue
        if "opus-4-7-policy.md" in body:
            old_refs.append(skill_md)
        if "../_shared/model-runtime-policy.md" not in body:
            nonportable_refs.append(skill_md)

    assert old_refs == []
    assert nonportable_refs == []


def test_version_resolution_never_reuses_base_version_for_new_payload(
    tmp_path, monkeypatch
) -> None:
    """A new payload hash must be newer than the fetched base's version."""
    builder = _load_builder()
    plugin_name = "collision-probe"
    plugin_dir = tmp_path / "marketplace" / plugin_name
    manifest_dir = plugin_dir / ".claude-plugin"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "plugin.json").write_text(
        json.dumps({"name": plugin_name, "version": "1.1.38"}) + "\n",
        encoding="utf-8",
    )
    (plugin_dir / "payload.txt").write_text("new payload\n", encoding="utf-8")
    ledger_path = tmp_path / "plugin-versions.json"
    ledger_path.write_text(
        json.dumps(
            {
                plugin_name: {
                    "version": "1.1.38",
                    "content_hash": "old-payload-hash",
                }
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(builder, "MARKETPLACE_DIR", tmp_path / "marketplace")
    monkeypatch.setattr(builder, "VERSION_LEDGER", ledger_path)
    monkeypatch.setattr(
        builder,
        "PLUGINS",
        [{"name": plugin_name, "version": "1.1.0"}],
    )
    monkeypatch.setattr(
        builder,
        "_load_base_version_ledger",
        lambda: {
            plugin_name: {
                "version": "1.1.38",
                "content_hash": "base-payload-hash",
            }
        },
    )
    monkeypatch.setattr(
        builder, "MIN_SAFE_PLUGIN_VERSIONS", {plugin_name: "1.1.39"}
    )

    resolved = builder.resolve_plugin_versions()

    assert resolved[plugin_name] == "1.1.39"
    persisted = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert persisted[plugin_name]["version"] == "1.1.39"
    assert persisted[plugin_name]["content_hash"] != "old-payload-hash"


def test_base_version_evidence_fails_closed_unless_offline_is_explicit(
    tmp_path, monkeypatch, capsys
) -> None:
    builder = _load_builder()
    plugin_name = "fixture"
    plugin_dir = tmp_path / "marketplace" / plugin_name
    manifest_dir = plugin_dir / ".claude-plugin"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "plugin.json").write_text(
        json.dumps({"name": plugin_name, "version": "1.0.0"}) + "\n",
        encoding="utf-8",
    )
    (plugin_dir / "payload.txt").write_text("payload\n", encoding="utf-8")
    monkeypatch.setattr(builder, "MARKETPLACE_DIR", tmp_path / "marketplace")
    monkeypatch.setattr(builder, "VERSION_LEDGER", tmp_path / "ledger.json")
    monkeypatch.setattr(
        builder,
        "PLUGINS",
        [{"name": plugin_name, "version": "1.0.0"}],
    )
    monkeypatch.setattr(builder, "MIN_SAFE_PLUGIN_VERSIONS", {})

    def unavailable():
        raise RuntimeError("origin/main version ledger unavailable")

    monkeypatch.setattr(builder, "_load_base_version_ledger", unavailable)

    with pytest.raises(RuntimeError, match="origin/main"):
        builder.resolve_plugin_versions()

    assert builder.resolve_plugin_versions(offline_non_release=True) == {
        plugin_name: "1.0.0"
    }
    assert "OFFLINE NON-RELEASE" in capsys.readouterr().err


def test_base_version_loader_rejects_missing_or_invalid_evidence(monkeypatch) -> None:
    builder = _load_builder()
    for completed in (
        subprocess.CompletedProcess(["git", "show"], 128, "", "missing ref"),
        subprocess.CompletedProcess(["git", "show"], 0, "not-json", ""),
        subprocess.CompletedProcess(["git", "show"], 0, "[]", ""),
    ):
        monkeypatch.setattr(builder.subprocess, "run", lambda *args, **kwargs: completed)
        with pytest.raises(RuntimeError, match="origin/main"):
            builder._load_base_version_ledger()


def test_release_cli_checks_base_evidence_before_building(monkeypatch) -> None:
    builder = _load_builder()
    built = []
    monkeypatch.setattr(
        builder,
        "PLUGINS",
        [{"name": "fixture", "description": "fixture", "version": "1.0.0", "files": []}],
    )
    monkeypatch.setattr(
        builder, "build_plugin", lambda plugin: built.append(plugin) or 0
    )

    def unavailable():
        raise RuntimeError("origin/main version ledger unavailable")

    monkeypatch.setattr(builder, "_load_base_version_ledger", unavailable)

    with pytest.raises(RuntimeError, match="origin/main"):
        builder.main([])

    assert built == []


def test_release_transaction_preserves_all_targets_on_late_gate_failure(
    tmp_path, monkeypatch
) -> None:
    builder = _load_builder()
    source = tmp_path / "source"
    marketplace = source / "marketplace"
    manifest_dir = source / ".claude-plugin"
    plugin_defs = []
    for name in ("early", "late"):
        skill = source / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(f"{name}\n", encoding="utf-8")
        (skill / "manifest.yaml").write_text(
            f"id: {name}\nrequires_skills: []\n", encoding="utf-8"
        )
        previous = marketplace / name
        previous.mkdir(parents=True)
        (previous / "last-known-good.txt").write_text(
            f"old {name}\n", encoding="utf-8"
        )
        plugin_defs.append(
            {
                "name": name,
                "description": name,
                "version": "1.0.0",
                "files": [(f"skills/{name}/SKILL.md", f"skills/{name}/SKILL.md")],
            }
        )
    manifest_dir.mkdir()
    (manifest_dir / "marketplace.json").write_text(
        "old marketplace\n", encoding="utf-8"
    )
    (manifest_dir / "plugin-versions.json").write_text(
        "old versions\n", encoding="utf-8"
    )

    def snapshot() -> dict[str, bytes]:
        targets = [marketplace, manifest_dir / "marketplace.json", manifest_dir / "plugin-versions.json"]
        result = {}
        for target in targets:
            if target.is_dir():
                result.update(
                    {
                        path.relative_to(source).as_posix(): path.read_bytes()
                        for path in sorted(target.rglob("*"))
                        if path.is_file()
                    }
                )
            elif target.is_file():
                result[target.relative_to(source).as_posix()] = target.read_bytes()
        return result

    before = snapshot()
    monkeypatch.setattr(builder, "CLAUDE_DIR", source)
    monkeypatch.setattr(builder, "MARKETPLACE_DIR", marketplace)
    monkeypatch.setattr(
        builder, "VERSION_LEDGER", manifest_dir / "plugin-versions.json"
    )
    monkeypatch.setattr(builder, "PLUGINS", plugin_defs)
    monkeypatch.setattr(builder, "MIN_SAFE_PLUGIN_VERSIONS", {})
    monkeypatch.setattr(
        builder,
        "_base_ledger_for_build",
        lambda *, offline_non_release: {},
    )
    monkeypatch.setattr(
        builder,
        "check_hook_import_containment",
        lambda: [("late", "broken.py", "missing_dependency")],
    )

    with pytest.raises(SystemExit) as exc:
        builder.main([])

    assert exc.value.code == 1
    assert snapshot() == before


def test_plugin_build_and_version_resolution_are_byte_idempotent(
    tmp_path, monkeypatch
) -> None:
    builder = _load_builder()
    source = tmp_path / "source"
    marketplace = tmp_path / "marketplace"
    skill = source / "skills" / "root"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("root\n", encoding="utf-8")
    (skill / "manifest.yaml").write_text(
        "id: root\nrequires_skills: []\n", encoding="utf-8"
    )
    plugin_def = {
        "name": "fixture",
        "description": "fixture",
        "version": "1.0.0",
        "files": [("skills/root/SKILL.md", "skills/root/SKILL.md")],
    }
    ledger = tmp_path / "plugin-versions.json"
    monkeypatch.setattr(builder, "CLAUDE_DIR", source)
    monkeypatch.setattr(builder, "MARKETPLACE_DIR", marketplace)
    monkeypatch.setattr(builder, "VERSION_LEDGER", ledger)
    monkeypatch.setattr(builder, "PLUGINS", [plugin_def])
    monkeypatch.setattr(builder, "MIN_SAFE_PLUGIN_VERSIONS", {})
    monkeypatch.setattr(builder, "_load_base_version_ledger", lambda: {})

    def snapshot() -> dict[str, bytes]:
        return {
            path.relative_to(marketplace).as_posix(): path.read_bytes()
            for path in sorted(marketplace.rglob("*"))
            if path.is_file()
        } | {"../plugin-versions.json": ledger.read_bytes()}

    builder.build_plugin(plugin_def)
    builder.resolve_plugin_versions()
    first = snapshot()
    builder.build_plugin(plugin_def)
    builder.resolve_plugin_versions()

    assert snapshot() == first


def test_content_hash_rejects_symlinked_payload(tmp_path) -> None:
    builder = _load_builder()
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n", encoding="utf-8")
    (plugin / "leak.txt").symlink_to(outside)

    with pytest.raises(ValueError, match="symlink"):
        builder._plugin_content_hash(plugin)


def test_known_cross_branch_collision_versions_have_safe_floors() -> None:
    builder = _load_builder()
    assert builder.MIN_SAFE_PLUGIN_VERSIONS == {
        "code-intelligence": "1.1.12",
        "knowledge-ops": "1.1.39",
        "planning-toolkit": "1.1.26",
        "research-intel": "1.1.17",
        "safety-net": "1.1.25",
        "security-scanner": "1.1.6",
    }


def test_security_plugin_metadata_does_not_advertise_nonpackageable_sca() -> None:
    builder = _load_builder()
    security = next(
        plugin for plugin in builder.PLUGINS if plugin["name"] == "security-scanner"
    )

    assert "SCA review" not in security["description"]


def test_temp_built_canonical_plugins_are_self_contained(
    tmp_path, monkeypatch
) -> None:
    """Acceptance test the real package graph without touching marketplace/."""
    builder = _load_builder()
    marketplace = tmp_path / "marketplace"
    monkeypatch.setattr(builder, "MARKETPLACE_DIR", marketplace)
    for plugin_def in builder.PLUGINS:
        builder.build_plugin(plugin_def)

    knowledge = marketplace / "knowledge-ops"
    security = marketplace / "security-scanner"
    planning = marketplace / "planning-toolkit"

    # Transitive skill composition: retro -> ship -> executable, and the
    # validation workflow's platform-refresh dependency.
    assert (knowledge / "skills" / "ship" / "SKILL.md").is_file()
    assert (
        knowledge / "skills" / "ship" / "scripts" / "outgoing_payload.py"
    ).is_file()
    assert (knowledge / "skills" / "gather-claude" / "SKILL.md").is_file()
    lock = json.loads(
        (knowledge / ".claude-plugin" / "dependency-lock.json").read_text(
            encoding="utf-8"
        )
    )
    assert "ship" in lock["requires_skills"]["retro"]
    assert lock["requires_skills"]["validate-changes"] == ["gather-claude"]

    # Shared assets are exact dependencies below a non-skill _shared tree.
    for relative in (
        "change-validation.md",
        "gather-conventions.md",
        "oracle/SPEC.md",
        "repo-map.md",
    ):
        assert (knowledge / "skills" / "_shared" / relative).is_file()
    for relative in (
        "adversarial-validation.md",
        "repo-map.md",
        "stig-common.md",
        "stig-targets/example-target.md",
        "model-overlays/mythos-5.md",
    ):
        assert (security / "skills" / "_shared" / relative).is_file()
    assert not (security / "skills" / "sca-review").exists()
    assert not list(marketplace.glob("*/skills/_shared/SKILL.md"))

    # Explicit root helpers plus their sibling dependency closure.
    for relative in (
        "bin/audit-skill-oracle.py",
        "bin/kb-dedup.py",
        "bin/transcript_friction.py",
        "bin/transcript_friction_corpus.py",
        "bin/transcript_recurrence.py",
        "scripts/_gather_screen.py",
        "scripts/retro-extract.py",
    ):
        assert (knowledge / relative).is_file()
    assert (planning / "bin" / "pr-merge-verified.py").is_file()

    # Cached Python remains syntactically executable after path normalization,
    # and no packaged text retains the personal ~/.claude skill prefix.
    for plugin_def in builder.PLUGINS:
        plugin = marketplace / plugin_def["name"]
        for source in builder._iter_text_files(plugin):
            body = source.read_text(encoding="utf-8")
            if source.suffix == ".py":
                compile(body, str(source), "exec")
                tree = ast.parse(body)
                assert not [
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Name)
                    and node.id == "CLAUDE_PLUGIN_ROOT"
                ], source
            else:
                assert "~/.claude/skills/" not in body, source
                assert "$HOME/.claude/skills/" not in body, source

    assert builder.check_skill_dependency_containment() == []
    assert builder.check_shared_asset_containment() == []
    assert builder.check_packaged_path_containment() == []

    env = {**os.environ, "CLAUDE_PLUGIN_ROOT": str(knowledge)}
    for relative in (
        "bin/audit-skill-oracle.py",
        "bin/transcript_friction_corpus.py",
        "scripts/_gather_screen.py",
        "skills/ship/scripts/outgoing_payload.py",
        "skills/validate-changes/scripts/change_contract.py",
    ):
        completed = subprocess.run(
            [sys.executable, str(knowledge / relative), "--help"],
            cwd=knowledge,
            env=env,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr


def test_packaged_healthcheck_uses_dependency_lock_in_isolated_home(
    tmp_path, monkeypatch
) -> None:
    builder = _load_builder()
    marketplace = tmp_path / "marketplace"
    monkeypatch.setattr(builder, "MARKETPLACE_DIR", marketplace)
    knowledge_def = next(
        plugin for plugin in builder.PLUGINS if plugin["name"] == "knowledge-ops"
    )
    builder.build_plugin(knowledge_def)
    plugin = marketplace / "knowledge-ops"
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    helper = plugin / "skills" / "healthcheck" / "references" / "_check_manifest.py"

    completed = subprocess.run(
        [sys.executable, str(helper)],
        cwd=plugin,
        env={
            **os.environ,
            "HOME": str(isolated_home),
            "CLAUDE_CONFIG_DIR": str(plugin),
            "CLAUDE_PLUGIN_ROOT": str(plugin),
        },
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "installed plugin dependency lock" in completed.stdout

    # Mutation: the same installed-mode check must fail closed when a locked
    # composed dependency disappears from the payload.
    (plugin / "skills" / "ship" / "SKILL.md").unlink()
    mutated = subprocess.run(
        [sys.executable, str(helper)],
        cwd=plugin,
        env={
            **os.environ,
            "HOME": str(isolated_home),
            "CLAUDE_CONFIG_DIR": str(plugin),
            "CLAUDE_PLUGIN_ROOT": str(plugin),
        },
        capture_output=True,
        text=True,
    )
    assert mutated.returncode == 2
    assert "locked skill is missing: ship" in mutated.stdout


def test_packaged_distill_and_audit_runtime_work_in_isolated_home(
    tmp_path, monkeypatch
) -> None:
    builder = _load_builder()
    marketplace = tmp_path / "marketplace"
    monkeypatch.setattr(builder, "MARKETPLACE_DIR", marketplace)
    knowledge_def = next(
        plugin for plugin in builder.PLUGINS if plugin["name"] == "knowledge-ops"
    )
    builder.build_plugin(knowledge_def)
    plugin = marketplace / "knowledge-ops"
    isolated_home = tmp_path / "home"
    isolated_home.mkdir()
    state_root = tmp_path / "state"
    cached_distill = (plugin / "skills" / "distill" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert (
        '${CLAUDE_PLUGIN_ROOT}/skills/distill/scripts/write_marker.py'
        in cached_distill
    )

    env = {
        **os.environ,
        "HOME": str(isolated_home),
        "CLAUDE_CONFIG_DIR": str(plugin),
        "CLAUDE_PLUGIN_ROOT": str(plugin),
        "AUDIT_SKILL_ORACLE_TRACE": str(tmp_path / "oracle-trace.jsonl"),
    }
    writer = plugin / "skills" / "distill" / "scripts" / "write_marker.py"
    distill = subprocess.run(
        [sys.executable, str(writer), "--clean", "--state-root", str(state_root)],
        cwd=plugin,
        env=env,
        capture_output=True,
        text=True,
    )
    assert distill.returncode == 0, distill.stdout + distill.stderr
    marker = json.loads((state_root / "last-distill.json").read_text(encoding="utf-8"))
    assert marker["lesson_count"] == 0

    packaged_audit = subprocess.run(
        [
            sys.executable,
            str(plugin / "bin" / "audit-skill.py"),
            "recall",
            "--no-marketplace-check",
            "--json",
        ],
        cwd=plugin,
        env=env,
        capture_output=True,
        text=True,
    )
    assert packaged_audit.returncode == 0, (
        packaged_audit.stdout + packaged_audit.stderr
    )
    assert json.loads(packaged_audit.stdout)["status"] == "OK"

    oracle = subprocess.run(
        [sys.executable, str(plugin / "bin" / "audit-skill-oracle.py"), "spec"],
        cwd=plugin,
        env=env,
        capture_output=True,
        text=True,
    )
    assert oracle.returncode == 0, oracle.stdout + oracle.stderr
    spec_path = Path(oracle.stdout.strip()).resolve()
    assert spec_path.is_relative_to(plugin.resolve())
    assert spec_path.is_file()


def test_package_containment_gates_kill_dependency_mutations(
    tmp_path, monkeypatch
) -> None:
    """Each gate must reject the broken artifact class it claims to cover."""
    builder = _load_builder()
    knowledge_def = next(
        plugin for plugin in builder.PLUGINS if plugin["name"] == "knowledge-ops"
    )
    marketplace = tmp_path / "marketplace"
    monkeypatch.setattr(builder, "MARKETPLACE_DIR", marketplace)
    monkeypatch.setattr(builder, "PLUGINS", [knowledge_def])
    plugin = marketplace / "knowledge-ops"

    builder.build_plugin(knowledge_def)
    (plugin / "skills" / "ship" / "SKILL.md").unlink()
    assert builder.check_skill_dependency_containment()

    builder.build_plugin(knowledge_def)
    (plugin / "skills" / "_shared" / "change-validation.md").unlink()
    assert builder.check_shared_asset_containment()

    builder.build_plugin(knowledge_def)
    (plugin / "bin" / "pr-merge-verified.py").unlink()
    assert builder.check_packaged_path_containment()

    builder.build_plugin(knowledge_def)
    skill_md = plugin / "skills" / "retro" / "SKILL.md"
    skill_md.write_text(
        skill_md.read_text(encoding="utf-8")
        + "\npython3 ~/.claude/skills/ship/scripts/outgoing_payload.py\n",
        encoding="utf-8",
    )
    assert builder.check_packaged_path_containment()


def test_built_model_policy_references_resolve_inside_each_plugin() -> None:
    _build_marketplace()
    representative_plugins = (
        ROOT / "marketplace" / "planning-toolkit",
        ROOT / "marketplace" / "research-intel",
        ROOT / "marketplace" / "security-scanner",
    )

    for plugin_root in representative_plugins:
        referenced = 0
        for skill_md in sorted(plugin_root.glob("skills/*/SKILL.md")):
            body = skill_md.read_text(encoding="utf-8")
            if "model-runtime-policy.md" not in body:
                continue
            referenced += 1
            target = (skill_md.parent / "../_shared/model-runtime-policy.md").resolve()
            assert target.is_relative_to(plugin_root.resolve())
            assert target.is_file()
        assert referenced > 0, f"representative plugin lacks policy consumer: {plugin_root}"

        for overlay in ("fable-5.md", "mythos-5.md", "opus-5.md", "sonnet-5.md"):
            assert (
                plugin_root / "skills" / "_shared" / "model-overlays" / overlay
            ).is_file()


def test_safety_net_registers_advertised_hook_inventory() -> None:
    """Every shipped safety hook must be wired to its intended lifecycle event."""
    _build_marketplace()

    hook_config = json.loads(
        (SAFETY_NET / "hooks" / "hooks.json").read_text(encoding="utf-8")
    )
    registrations = set()
    for event, groups in hook_config["hooks"].items():
        for group in groups:
            matcher = group.get("matcher", "")
            for handler in group["hooks"]:
                registrations.add(
                    (
                        event,
                        matcher,
                        handler["command"],
                        tuple(handler["args"]),
                        handler["timeout"],
                    )
                )

    expected = {
        (
            "PreToolUse",
            "Bash",
            "bash",
            (
                "${CLAUDE_PLUGIN_ROOT}/hooks/run-hook",
                "bash-security-guard.py",
            ),
            30,
        ),
        (
            "PreToolUse",
            "Write|Edit",
            "bash",
            ("${CLAUDE_PLUGIN_ROOT}/hooks/run-hook", "config-guard.py"),
            30,
        ),
        (
            "PreToolUse",
            "Write|Edit",
            "bash",
            ("${CLAUDE_PLUGIN_ROOT}/hooks/run-hook", "memory-write-guard.py"),
            30,
        ),
        (
            "PreToolUse",
            "Glob|Grep",
            "bash",
            ("${CLAUDE_PLUGIN_ROOT}/hooks/run-hook", "search-path-guard.py"),
            30,
        ),
        (
            "PreToolUse",
            "Read",
            "bash",
            ("${CLAUDE_PLUGIN_ROOT}/hooks/run-hook", "block-partial-read.py"),
            30,
        ),
        (
            "PostToolUse",
            "Write|Edit",
            "bash",
            ("${CLAUDE_PLUGIN_ROOT}/hooks/run-hook", "post-write-edit.py"),
            30,
        ),
        (
            "PostToolUse",
            "mcp__.*",
            "bash",
            ("${CLAUDE_PLUGIN_ROOT}/hooks/run-hook", "result-injection-guard.py"),
            30,
        ),
        (
            "PostToolUse",
            "mcp__.*|Bash|Read|Glob|Grep",
            "bash",
            ("${CLAUDE_PLUGIN_ROOT}/hooks/run-hook", "loop-detector.py"),
            20,
        ),
        (
            "PostToolUse",
            "Bash",
            "bash",
            ("${CLAUDE_PLUGIN_ROOT}/hooks/run-hook", "bash-security-audit.py"),
            30,
        ),
        (
            "PostToolUse",
            "mcp__.*|Bash|Read|Write|Edit|Glob|Grep",
            "bash",
            ("${CLAUDE_PLUGIN_ROOT}/hooks/run-hook", "context-monitor.py"),
            20,
        ),
        (
            "PostToolUseFailure",
            "mcp__.*|Bash|Read|Edit|Write",
            "bash",
            ("${CLAUDE_PLUGIN_ROOT}/hooks/run-hook", "post-failure-guide.py"),
            20,
        ),
        (
            "PostToolUseFailure",
            "Bash",
            "bash",
            ("${CLAUDE_PLUGIN_ROOT}/hooks/run-hook", "bash-error-classifier.py"),
            30,
        ),
        (
            "PreCompact",
            "",
            "bash",
            ("${CLAUDE_PLUGIN_ROOT}/hooks/run-hook", "precompact-checkpoint.py"),
            20,
        ),
        (
            "Stop",
            "",
            "bash",
            ("${CLAUDE_PLUGIN_ROOT}/hooks/run-hook", "promise-checker.py"),
            20,
        ),
    }

    assert registrations == expected


def test_safety_net_hook_timeouts_match_canonical_budgets() -> None:
    """Marketplace hooks must retain main's measured timeout safety margin."""
    _build_marketplace()

    hook_config = json.loads(
        (SAFETY_NET / "hooks" / "hooks.json").read_text(encoding="utf-8")
    )
    packaged_timeouts = {
        handler["args"][-1]: handler["timeout"]
        for groups in hook_config["hooks"].values()
        for group in groups
        for handler in group["hooks"]
    }

    settings = json.loads((ROOT / "settings.json").read_text(encoding="utf-8"))
    canonical_timeouts = {}
    for groups in settings["hooks"].values():
        for group in groups:
            for handler in group["hooks"]:
                command = handler.get("command", "")
                args = handler.get("args", [])
                for script in packaged_timeouts:
                    if command.endswith(f" {script}") or (
                        isinstance(args, list) and args and args[-1] == script
                    ):
                        canonical_timeouts[script] = handler["timeout"]

    # These guards are plugin-only registrations. The blocking guards use the
    # 30-second tier; the advisory context/compaction hooks use 20 seconds.
    canonical_timeouts["config-guard.py"] = 30
    canonical_timeouts["memory-write-guard.py"] = 30
    canonical_timeouts["context-monitor.py"] = 20
    canonical_timeouts["precompact-checkpoint.py"] = 20

    assert packaged_timeouts == canonical_timeouts


def test_safety_net_does_not_ship_inert_rules_directory() -> None:
    """Plugin instructions must use recognized components, not dead payload."""
    _build_marketplace()

    assert not (SAFETY_NET / "rules").exists()


def test_readme_describes_installable_safety_net_components() -> None:
    """Marketplace docs must only promise components Claude actually loads.

    Asserts the CLAIM'S SHAPE, not a count. This previously pinned the literal
    "14 hooks + 3 skills", which made every added hook or skill fail a test whose
    stated intent is about WHICH KINDS of component the plugin ships — the count
    was never the invariant, just the wording that happened to carry it. All
    hardcoded count claims were removed from README/ARCHITECTURE on 2026-07-29
    because a hand-maintained count is a drift generator; re-pinning one here
    would reintroduce it through the back door.

    What must hold: the safety-net row exists, and it promises hooks and skills
    (the two component kinds Claude loads for that plugin) and nothing else.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    row = next((l for l in readme.splitlines()
                if l.startswith("| `safety-net` |")), None)
    assert row is not None, "README lost its safety-net plugin row"
    assert "hooks" in row and "skills" in row, (
        f"safety-net row must promise hooks + skills, got: {row}"
    )
    # Guard the original intent: do not promise a component kind the plugin
    # cannot deliver (agents/rules are not loaded from this plugin).
    assert "agents" not in row, f"safety-net promises agents it does not ship: {row}"


def test_packaged_bash_security_guard_fires_through_launcher() -> None:
    """The built plugin must execute a blocking hook without source-tree help."""
    _build_marketplace()
    bash = shutil.which("bash")
    assert bash is not None, "Claude Code hook launcher requires bash"
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "cat ~/.aws/credentials"},
            "cwd": str(ROOT),
        }
    )

    completed = subprocess.run(
        [
            bash,
            str(SAFETY_NET / "hooks" / "run-hook"),
            "bash-security-guard.py",
        ],
        cwd=SAFETY_NET,
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 2
    assert "BLOCKED" in completed.stderr


def test_ci_runs_strict_claude_plugin_validation() -> None:
    """Generated bundles must be checked by Claude's own pinned validator."""
    workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(
        encoding="utf-8"
    )

    assert "@anthropic-ai/claude-code@2.1.226" in workflow
    assert "claude plugin validate . --strict" in workflow
    assert 'claude plugin validate "$plugin" --strict' in workflow


def test_ci_fetches_base_history_for_fail_closed_version_evidence() -> None:
    workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(
        encoding="utf-8"
    )

    checkout = workflow.index("uses: actions/checkout@")
    setup_python = workflow.index("uses: actions/setup-python@", checkout)
    assert "fetch-depth: 0" in workflow[checkout:setup_python]


def _packaging_obligation_fixture(tmp_path, monkeypatch, leaf: str):
    """Build a source+plugin pair where `leaf` exists canonically but is unpackaged.

    Mirrors the real shape: the packaged SKILL.md has already been rewritten to
    the ${CLAUDE_PLUGIN_ROOT} form, which is what the reference regex matches.
    """
    builder = _load_builder()
    source = tmp_path / "source"
    canonical = source / "skills" / "root"
    (canonical / "state").mkdir(parents=True)
    (canonical / "state" / leaf).write_text("{}\n", encoding="utf-8")
    (canonical / "SKILL.md").write_text("root\n", encoding="utf-8")

    plugin = tmp_path / "plugin"
    packaged = plugin / "skills" / "root"
    packaged.mkdir(parents=True)
    (packaged / "SKILL.md").write_text(
        "Writes ${CLAUDE_PLUGIN_ROOT}/skills/root/state/" + leaf + " on each run.\n",
        encoding="utf-8",
    )
    # deliberately NOT packaged -- that is the copy layer's decision
    monkeypatch.setattr(builder, "CLAUDE_DIR", source)
    return builder, plugin


def test_excluded_runtime_state_creates_no_packaging_obligation(
    tmp_path, monkeypatch
) -> None:
    """A SKILL_COPY_EXCLUDE_NAMES leaf must not be required in the plugin.

    The copy layer refuses to ship machine-local runtime state, so demanding it
    here is unsatisfiable: on any host where the producing skill has run, the
    file exists canonically and the build can never succeed. CI never sees it
    because a fresh checkout has no runtime state.
    """
    builder, plugin = _packaging_obligation_fixture(
        tmp_path, monkeypatch, "unmapped-history.jsonl"
    )
    assert "unmapped-history.jsonl" in builder.SKILL_COPY_EXCLUDE_NAMES

    assert builder._plugin_skill_path_problems("fixture", plugin) == []


def test_unexcluded_missing_target_is_still_reported(tmp_path, monkeypatch) -> None:
    """Known-positive control: the check must still fire for a normal asset.

    Without this, the test above could pass because the checker stopped working
    entirely rather than because the exclusion is honoured.
    """
    builder, plugin = _packaging_obligation_fixture(
        tmp_path, monkeypatch, "shipped-asset.json"
    )
    assert "shipped-asset.json" not in builder.SKILL_COPY_EXCLUDE_NAMES

    problems = builder._plugin_skill_path_problems("fixture", plugin)
    assert len(problems) == 1, problems
    assert "missing packaged skill target" in problems[0][2]
    assert "shipped-asset.json" in problems[0][2]
