from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-profile.py"


def _load_installer():
    spec = importlib.util.spec_from_file_location("install_profile", INSTALLER)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


installer = _load_installer()


def _run(target: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(INSTALLER), "--target", str(target), *extra],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_preview_is_read_only_and_does_not_print_existing_values(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    original = {"env": {"PRIVATE_TOKEN": "do-not-print"}, "hooks": {"Stop": []}}
    target.write_text(json.dumps(original), encoding="utf-8")

    result = _run(target)

    assert result.returncode == 0, result.stderr
    assert json.loads(target.read_text(encoding="utf-8")) == original
    assert "do-not-print" not in result.stdout
    assert "No files written" in result.stdout


def test_apply_preserves_unmanaged_keys_and_creates_backup(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    original = {"env": {"KEEP": "1"}, "hooks": {"Stop": []}}
    target.write_text(json.dumps(original), encoding="utf-8")

    result = _run(target, "--apply")

    assert result.returncode == 0, result.stderr
    merged = json.loads(target.read_text(encoding="utf-8"))
    assert merged["env"] == original["env"]
    assert merged["hooks"] == original["hooks"]
    assert merged["permissions"]["defaultMode"] == "acceptEdits"
    assert merged["sandbox"]["enabled"] is True
    assert merged["sandbox"]["allowUnsandboxedCommands"] is True
    backups = list(tmp_path.glob("settings.json.bak.*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == original


def test_apply_is_idempotent_after_first_write(tmp_path: Path) -> None:
    target = tmp_path / "settings.json"
    first = _run(target, "--apply")
    second = _run(target, "--apply")

    assert first.returncode == second.returncode == 0
    assert "already matches" in second.stdout
    assert not list(tmp_path.glob("settings.json.bak.*"))


def test_apply_appends_permission_lists_instead_of_replacing(tmp_path: Path) -> None:
    """Measured 2026-09-03: applying fresh-laptop over a curated settings.json cut
    permissions.allow from 34 entries to 3. Profile lists union with the existing
    ones so a user's own allow/deny decisions survive the merge."""
    target = tmp_path / "settings.json"
    original = {"permissions": {"allow": ["Bash(gitleaks detect *)"], "deny": ["Read(~/.private/**)"]}}
    target.write_text(json.dumps(original), encoding="utf-8")

    result = _run(target, "--apply")

    assert result.returncode == 0, result.stderr
    merged = json.loads(target.read_text(encoding="utf-8"))
    assert "Bash(gitleaks detect *)" in merged["permissions"]["allow"]
    assert "Read(~/.private/**)" in merged["permissions"]["deny"]
    assert "Edit(~/.ssh/**)" in merged["permissions"]["deny"]
    assert len(merged["permissions"]["deny"]) == len(set(merged["permissions"]["deny"]))


def test_fresh_laptop_profile_grants_no_allow_entries() -> None:
    """Read, Glob and Grep never prompt, so an allow entry for them is a no-op
    that reads as if the profile grants something. It must not carry one."""
    profile = json.loads((ROOT / "profiles" / "fresh-laptop" / "settings.json").read_text(encoding="utf-8"))
    assert "allow" not in profile["permissions"]


# ── --install brings a file's local dependencies ──────────────────────────
#
# 2026-09-04 incident: `--install hooks/bash-security-guard.py --apply` upgraded
# the guard alone. The new guard does `from _environment_catalog import ...`, a
# sibling module the older install had never received, so the installed guard
# crashed on import; hooks/bash-pretooluse-dispatcher.py fails closed on a hook
# crash (correct for a guard), so every Bash command was blocked until the
# loader was copied in by hand. A targeted install must bring what the file
# imports and what its manifest declares, transitively.


def test_guard_dependency_closure_against_the_real_checkout() -> None:
    additions = dict(installer.dependency_closure(ROOT, ["hooks/bash-security-guard.py"]))

    assert "hooks/_environment_catalog.py" in additions
    assert additions["hooks/_environment_catalog.py"] == "imported by hooks/bash-security-guard.py"
    assert "hooks/bash_policy_tables.py" in additions  # module-level import
    assert "hooks/manifest_metrics.py" in additions  # imported inside a function body
    # hooks/manifests/bash-security-guard.yaml spells one entry repo-relative and one hooks-relative.
    assert additions["contracts/environment-catalog.json"] == "declared by hooks/manifests/bash-security-guard.yaml"
    assert additions["hooks/protected-repos.json"] == "declared by hooks/manifests/bash-security-guard.yaml"
    assert "hooks/bash-security-guard.py" not in additions


@pytest.fixture()
def checkout(tmp_path: Path) -> Path:
    """a imports b; b imports c and os; c imports nothing; a's manifest declares contracts/x.json."""
    root = tmp_path / "checkout"
    (root / "hooks" / "manifests").mkdir(parents=True)
    (root / "contracts").mkdir()
    (root / "hooks" / "a.py").write_text("import b\n", encoding="utf-8")
    (root / "hooks" / "b.py").write_text("import os\nfrom c import thing\n", encoding="utf-8")
    (root / "hooks" / "c.py").write_text("thing = 1\n", encoding="utf-8")
    (root / "hooks" / "manifests" / "a.yaml").write_text(
        "id: a\ndepends_on_files:\n  - contracts/x.json\nexit_codes: {}\n", encoding="utf-8")
    (root / "contracts" / "x.json").write_text("{}\n", encoding="utf-8")
    return root


def test_closure_follows_imports_transitively_and_manifest_declarations(checkout: Path) -> None:
    additions = installer.dependency_closure(checkout, ["hooks/a.py"])

    rels = [rel for rel, _reason in additions]
    assert set(rels) == {"hooks/b.py", "hooks/c.py", "contracts/x.json"}
    assert len(rels) == len(set(rels)), "each dependency is listed once"
    assert "os" not in {Path(rel).stem for rel in rels}, "stdlib names have no sibling file and never appear"
    reasons = dict(additions)
    assert reasons["hooks/b.py"] == "imported by hooks/a.py"
    assert reasons["hooks/c.py"] == "imported by hooks/b.py"
    assert reasons["contracts/x.json"] == "declared by hooks/manifests/a.yaml"


def test_import_without_a_sibling_file_is_ignored(checkout: Path) -> None:
    """Locality is decided by the sibling file existing, not by importability:
    a third-party or stdlib name never becomes an install target."""
    (checkout / "hooks" / "a.py").write_text(
        "import b\nimport requests\nfrom nosuch_module import x\n", encoding="utf-8")

    rels = {rel for rel, _reason in installer.dependency_closure(checkout, ["hooks/a.py"])}

    assert rels == {"hooks/b.py", "hooks/c.py", "contracts/x.json"}


def test_package_import_installs_the_whole_package_and_its_own_imports(checkout: Path) -> None:
    """`from pkg.sub import x` needs pkg/__init__.py AND pkg/sub.py; a package is
    installed as a unit (every file beneath it, __pycache__ skipped). A module
    inside the package resolves siblings against hooks/ too, the way
    session_start_modules/*.py import _environment_catalog."""
    pkg = checkout / "hooks" / "pkg"
    (pkg / "__pycache__").mkdir(parents=True)
    (pkg / "__pycache__" / "sub.cpython-313.pyc").write_bytes(b"\x00")
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "sub.py").write_text("from _shared import x\n", encoding="utf-8")
    (checkout / "hooks" / "_shared.py").write_text("x = 1\n", encoding="utf-8")
    (checkout / "hooks" / "a.py").write_text("from pkg.sub import x\n", encoding="utf-8")

    rels = {rel for rel, _reason in installer.dependency_closure(checkout, ["hooks/a.py"])}

    assert rels == {"hooks/pkg/__init__.py", "hooks/pkg/sub.py", "hooks/_shared.py", "contracts/x.json"}


def test_manifest_entries_resolve_repo_or_hooks_relative_and_skip_runtime_paths(checkout: Path, tmp_path: Path) -> None:
    """The real manifests spell depends_on_files three ways: repo-relative
    (contracts/environment-catalog.json), hooks-relative (bash_policy_tables.py)
    and as a glob (hooks/session_start_modules/*.py). They also list runtime
    paths (~/.claude/settings.json) and prose, which are not in the checkout and
    must be skipped, as must anything that escapes the checkout."""
    (checkout / "hooks" / "data.json").write_text("{}\n", encoding="utf-8")
    (checkout / "hooks" / "mods").mkdir()
    (checkout / "hooks" / "mods" / "m1.py").write_text("", encoding="utf-8")
    (checkout / "hooks" / "mods" / "m2.py").write_text("", encoding="utf-8")
    (tmp_path / "escape.py").write_text("", encoding="utf-8")
    (checkout / "hooks" / "manifests" / "a.yaml").write_text(
        "id: a\n"
        "depends_on_files:\n"
        "  - data.json\n"
        "  - hooks/c.py\n"
        "  - hooks/mods/*.py\n"
        '  - "~/.claude/settings.json"\n'
        '  - "session transcript JSONL (read-only, for prior getschema detection)"\n'
        "  - ../escape.py\n"
        "depends_on_env: []\n",
        encoding="utf-8",
    )

    rels = {rel for rel, _reason in installer.dependency_closure(checkout, ["hooks/a.py"])}

    assert rels == {"hooks/b.py", "hooks/c.py", "hooks/data.json", "hooks/mods/m1.py", "hooks/mods/m2.py"}


def test_manifest_reader_agrees_with_pyyaml_on_every_real_manifest() -> None:
    """The installer must run on a fresh laptop with the stdlib only, so it reads
    depends_on_files with a small block reader instead of PyYAML. Parity with
    PyYAML over every committed manifest is the control for that reader."""
    yaml = pytest.importorskip("yaml")
    manifests = sorted((ROOT / "hooks" / "manifests").glob("*.yaml"))
    assert len(manifests) > 40, "expected the full manifest set"
    for manifest in manifests:
        expected = yaml.safe_load(manifest.read_text(encoding="utf-8")).get("depends_on_files") or []
        assert installer.manifest_dependencies(manifest) == [str(entry) for entry in expected], manifest.name


def _install(checkout: Path, config: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(INSTALLER), "--target", str(config / "settings.json"),
         "--source-root", str(checkout), "--install", "hooks/a.py", *extra],
        cwd=ROOT, capture_output=True, text=True, timeout=30, check=False)


def test_install_of_one_hook_brings_and_records_its_dependencies(checkout: Path, tmp_path: Path) -> None:
    config = tmp_path / ".claude"
    config.mkdir()

    preview = _install(checkout, config)
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert "also installing hooks/b.py (imported by hooks/a.py)" in preview.stdout
    assert "also installing contracts/x.json (declared by hooks/manifests/a.yaml)" in preview.stdout
    assert "4 NEW" in preview.stdout, preview.stdout
    assert not (config / "hooks").exists(), "preview writes nothing"

    result = _install(checkout, config, "--apply")
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.count("also installing hooks/b.py") == 1
    assert "also installing hooks/c.py (imported by hooks/b.py)" in result.stdout
    for rel in ("hooks/a.py", "hooks/b.py", "hooks/c.py", "contracts/x.json"):
        assert (config / rel).is_file(), rel
    files = json.loads((config / ".harness-install-state.json").read_text(encoding="utf-8"))["files"]
    assert set(files) == {"hooks/a.py", "hooks/b.py", "hooks/c.py", "contracts/x.json"}
    assert files["hooks/b.py"]["sha256"] == hashlib.sha256((checkout / "hooks" / "b.py").read_bytes()).hexdigest()
    assert files["hooks/b.py"].keys() == files["hooks/a.py"].keys(), "a dependency is recorded exactly like an explicit target"
    assert "4 NEW" in result.stdout, result.stdout


def test_dependency_that_the_user_edited_keeps_the_merge_contract(checkout: Path, tmp_path: Path) -> None:
    """Expansion changes which files are considered, never how each one is
    classified: an edited dependency is kept and the upstream version lands
    beside it as .harness-new, exactly as for an explicit target."""
    config = tmp_path / ".claude"
    config.mkdir()
    assert _install(checkout, config, "--apply").returncode == 0
    (config / "hooks" / "c.py").write_text("thing = 'mine'\n", encoding="utf-8")
    (checkout / "hooks" / "c.py").write_text("thing = 2\n", encoding="utf-8")

    result = _install(checkout, config, "--apply")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (config / "hooks" / "c.py").read_text(encoding="utf-8") == "thing = 'mine'\n"
    assert (config / "hooks" / "c.py.harness-new").read_text(encoding="utf-8") == "thing = 2\n"
    assert "CONFLICT hooks/c.py" in result.stdout, result.stdout
