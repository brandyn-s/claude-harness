"""Hash-manifest install state for scripts/install-profile.py --install.

Every file the installer writes is recorded in
<config_root>/.harness-install-state.json with its sha256, so a later install
can tell an untouched copy from a user edit instead of asking "overwrite?".
Classification (proved below):

    NEW               target absent                              -> write
    UNCHANGED         target == recorded hash (or == new bytes)  -> write
    MODIFIED-BY-USER  target != recorded, new == recorded        -> keep, report
    CONFLICT          target != recorded, new != recorded        -> keep, write
                      <name>.harness-new beside it, report
    (no record)       == new -> UNCHANGED, else -> CONFLICT
    --force           write everything regardless

    --install DIR     every regular file beneath it (``__pycache__`` skipped),
                      one record each; an empty directory is an error

settings.json is never hash-classified; it keeps the union merge.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-profile.py"
INSTALL_SH = ROOT / "install.sh"
MANIFEST = ".harness-install-state.json"
FILES = ("rules/a.md", "hooks/run-hook")


def sha(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def run(config: Path, source: Path, *extra: str, files: tuple[str, ...] = FILES,
        apply: bool = True) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(INSTALLER), "--target", str(config / "settings.json"),
            "--source-root", str(source)]
    for rel in files:
        args += ["--install", rel]
    if apply:
        args.append("--apply")
    args += extra
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False, timeout=30)


def manifest(config: Path) -> dict:
    return json.loads((config / MANIFEST).read_text(encoding="utf-8"))


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    src = tmp_path / "upstream"
    (src / "rules").mkdir(parents=True)
    (src / "hooks").mkdir()
    (src / "rules" / "a.md").write_text("rule a v1\n", encoding="utf-8")
    hook = src / "hooks" / "run-hook"
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
    return src


@pytest.fixture()
def config(tmp_path: Path) -> Path:
    cfg = tmp_path / ".claude"
    cfg.mkdir()
    return cfg


def test_fresh_install_records_hashes(config: Path, source: Path) -> None:
    result = run(config, source)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (config / "rules" / "a.md").read_text(encoding="utf-8") == "rule a v1\n"
    assert os.access(config / "hooks" / "run-hook", os.X_OK), "source mode must survive the copy"
    files = manifest(config)["files"]
    assert set(files) == set(FILES)
    assert files["rules/a.md"]["sha256"] == sha("rule a v1\n")
    assert files["hooks/run-hook"]["sha256"] == sha((source / "hooks" / "run-hook").read_bytes())
    assert files["rules/a.md"]["installed_at"].endswith("+00:00")
    assert files["rules/a.md"]["profiles"] == []
    assert "2 NEW" in result.stdout, result.stdout


def test_reinstall_of_identical_content_is_unchanged(config: Path, source: Path) -> None:
    run(config, source)
    result = run(config, source)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 UNCHANGED" in result.stdout, result.stdout
    assert "NEW" not in result.stdout.replace(".harness-new", "")
    assert not list(config.rglob("*.harness-new"))
    assert set(manifest(config)["files"]) == set(FILES)


def test_user_edited_file_is_preserved_and_reported(config: Path, source: Path) -> None:
    run(config, source)
    (config / "rules" / "a.md").write_text("rule a, my edit\n", encoding="utf-8")

    result = run(config, source)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (config / "rules" / "a.md").read_text(encoding="utf-8") == "rule a, my edit\n"
    assert "MODIFIED-BY-USER rules/a.md" in result.stdout, result.stdout
    assert "1 MODIFIED-BY-USER" in result.stdout and "1 UNCHANGED" in result.stdout
    assert not (config / "rules" / "a.md.harness-new").exists()
    # The record still describes what the installer last wrote, so the next run
    # classifies the same way instead of silently adopting the edit.
    assert manifest(config)["files"]["rules/a.md"]["sha256"] == sha("rule a v1\n")


def test_upstream_change_over_untouched_copy_is_overwritten(config: Path, source: Path) -> None:
    run(config, source)
    (source / "rules" / "a.md").write_text("rule a v2\n", encoding="utf-8")

    result = run(config, source)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (config / "rules" / "a.md").read_text(encoding="utf-8") == "rule a v2\n"
    assert "2 UNCHANGED" in result.stdout, result.stdout
    assert manifest(config)["files"]["rules/a.md"]["sha256"] == sha("rule a v2\n")


def test_both_changed_produces_harness_new_and_conflict_line(config: Path, source: Path) -> None:
    run(config, source)
    (config / "rules" / "a.md").write_text("rule a, my edit\n", encoding="utf-8")
    (source / "rules" / "a.md").write_text("rule a v2\n", encoding="utf-8")

    result = run(config, source)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (config / "rules" / "a.md").read_text(encoding="utf-8") == "rule a, my edit\n"
    assert (config / "rules" / "a.md.harness-new").read_text(encoding="utf-8") == "rule a v2\n"
    assert "CONFLICT rules/a.md" in result.stdout, result.stdout
    assert "rules/a.md.harness-new" in result.stdout
    assert "1 CONFLICT" in result.stdout
    assert manifest(config)["files"]["rules/a.md"]["sha256"] == sha("rule a v1\n")
    assert "rules/a.md.harness-new" not in manifest(config)["files"]


def test_force_overwrites_regardless(config: Path, source: Path) -> None:
    run(config, source)
    (config / "rules" / "a.md").write_text("rule a, my edit\n", encoding="utf-8")
    (source / "rules" / "a.md").write_text("rule a v2\n", encoding="utf-8")

    result = run(config, source, "--force")

    assert result.returncode == 0, result.stdout + result.stderr
    assert (config / "rules" / "a.md").read_text(encoding="utf-8") == "rule a v2\n"
    assert not (config / "rules" / "a.md.harness-new").exists()
    assert "force" in result.stdout.lower()
    assert manifest(config)["files"]["rules/a.md"]["sha256"] == sha("rule a v2\n")


def test_legacy_file_without_record_equal_to_upstream_is_unchanged(config: Path, source: Path) -> None:
    (config / "rules").mkdir()
    (config / "rules" / "a.md").write_text("rule a v1\n", encoding="utf-8")

    result = run(config, source, files=("rules/a.md",))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 UNCHANGED" in result.stdout, result.stdout
    assert manifest(config)["files"]["rules/a.md"]["sha256"] == sha("rule a v1\n")


def test_legacy_file_without_record_that_differs_is_conflict(config: Path, source: Path) -> None:
    (config / "rules").mkdir()
    (config / "rules" / "a.md").write_text("installed long ago, then edited\n", encoding="utf-8")

    result = run(config, source, files=("rules/a.md",))

    assert result.returncode == 0, result.stdout + result.stderr
    assert (config / "rules" / "a.md").read_text(encoding="utf-8") == "installed long ago, then edited\n"
    assert (config / "rules" / "a.md.harness-new").read_text(encoding="utf-8") == "rule a v1\n"
    assert "CONFLICT rules/a.md" in result.stdout, result.stdout
    assert "rules/a.md" not in manifest(config)["files"]


def test_settings_json_is_merged_not_hash_classified(config: Path, source: Path) -> None:
    (config / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(gitleaks detect *)"]}}), encoding="utf-8")

    result = run(config, source, "--profile", "fresh-laptop", files=("rules/a.md",))

    assert result.returncode == 0, result.stdout + result.stderr
    settings = json.loads((config / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["defaultMode"] == "acceptEdits"
    assert "Bash(gitleaks detect *)" in settings["permissions"]["allow"]
    files = manifest(config)["files"]
    assert "settings.json" not in files
    assert files["rules/a.md"]["profiles"] == ["fresh-laptop"]


def test_install_without_profile_leaves_settings_alone(config: Path, source: Path) -> None:
    result = run(config, source)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (config / "settings.json").exists()
    assert "(none)" in result.stdout


def test_preview_classifies_but_writes_nothing(config: Path, source: Path) -> None:
    result = run(config, source, apply=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 NEW" in result.stdout
    assert "No files written" in result.stdout
    assert not (config / "rules").exists()
    assert not (config / MANIFEST).exists()


def test_rejects_escaping_paths_and_the_settings_target(config: Path, source: Path) -> None:
    (source / "escape.md").write_text("x", encoding="utf-8")
    assert run(config, source, files=("rules/../escape.md",)).returncode == 2
    assert run(config, source, files=("/etc/hosts",)).returncode == 2
    (source / "settings.json").write_text("{}", encoding="utf-8")
    assert run(config, source, files=("settings.json",)).returncode == 2
    assert run(config, source, files=("rules/missing.md",)).returncode == 2
    assert not (config / MANIFEST).exists()


# ── install.sh routes the starter kit through the classified copy ─────────

BASH = shutil.which("bash")
pytestmark_bash = pytest.mark.skipif(
    BASH is None or sys.platform == "win32", reason="install.sh needs POSIX bash")


def test_install_sh_routes_every_component_through_the_classified_copy() -> None:
    """Every installer copies through install_files (the manifest), not cp.

    The starter kit was routed first; the optional installers (rules, skills,
    hooks, agents, agent-memory, ARCHITECTURE.md) still used cp, so a re-run
    overwrote a user's edits to any of those files. The one cp left is the
    CLAUDE.template.md -> CLAUDE.md rename, which only runs when CLAUDE.md is
    absent and so can never overwrite anything.
    """
    src = INSTALL_SH.read_text(encoding="utf-8")
    copies = [line.strip() for line in src.splitlines() if re.match(r"\s*cp\b", line)]
    assert copies == ['cp "$SCRIPT_DIR/CLAUDE.template.md" "$CLAUDE_DIR/CLAUDE.md"'], copies
    assert 'install_args+=(--install "$f")' in src
    assert 'install_files "${starter_files[@]}"' in src, "the starter copy must feed from the shared manifest"
    for installer in ("install_rules", "install_skills", "install_hooks", "install_agents",
                      "install_agent_memory", "install_architecture_doc"):
        start = src.index(f"{installer}() {{")
        body = src[start:src.index("\n}\n", start)]
        assert "install_files " in body, f"{installer} does not copy through the manifest"


@pytestmark_bash
def test_install_sh_rerun_keeps_a_local_edit_and_records_state(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    config = tmp_path / ".claude"

    def install(answers: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [BASH, str(INSTALL_SH)], input=answers, cwd=ROOT, env=env,
            capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)

    # skip profile, starter core, wire hooks, skip repo githooks, stop
    first = install("n\ny\ny\nn\nn\n")
    assert first.returncode == 0, first.stdout + first.stderr
    files = manifest(config)["files"]
    assert "rules/outcome-over-verification.md" in files
    assert "hooks/run-hook" in files
    assert os.access(config / "hooks" / "run-hook", os.X_OK)

    rule = config / "rules" / "outcome-over-verification.md"
    rule.write_text("my local edit\n", encoding="utf-8")

    # skip profile, starter core, UPGRADE existing, wire hooks, skip githooks, stop
    second = install("n\ny\ny\ny\nn\nn\n")
    assert second.returncode == 0, second.stdout + second.stderr
    assert rule.read_text(encoding="utf-8") == "my local edit\n"
    assert "MODIFIED-BY-USER rules/outcome-over-verification.md" in second.stdout
    assert not rule.with_name(rule.name + ".harness-new").exists()
    settings = json.loads((config / "settings.json").read_text(encoding="utf-8"))
    assert settings["hooks"], "kept files still count as present, so hooks are wired"


# ── --install of a directory (skills, agent-memory, session_start_modules) ─

def test_directory_install_records_every_file_beneath_it(config: Path, source: Path) -> None:
    skill = source / "skills" / "demo"
    (skill / "scripts").mkdir(parents=True)
    (skill / "SKILL.md").write_text("demo v1\n", encoding="utf-8")
    tool = skill / "scripts" / "tool.py"
    tool.write_text("print(1)\n", encoding="utf-8")
    tool.chmod(0o755)
    cache = skill / "scripts" / "__pycache__"
    cache.mkdir()
    (cache / "tool.cpython-313.pyc").write_bytes(b"\x00")

    result = run(config, source, files=("skills/demo",))

    assert result.returncode == 0, result.stdout + result.stderr
    assert (config / "skills" / "demo" / "SKILL.md").read_text(encoding="utf-8") == "demo v1\n"
    assert os.access(config / "skills" / "demo" / "scripts" / "tool.py", os.X_OK)
    assert not (config / "skills" / "demo" / "scripts" / "__pycache__").exists()
    assert set(manifest(config)["files"]) == {"skills/demo/SKILL.md", "skills/demo/scripts/tool.py"}
    assert "2 NEW" in result.stdout, result.stdout


def test_directory_reinstall_stays_flat_and_classifies_per_file(config: Path, source: Path) -> None:
    """`cp -r src/skill dest/skill` into an EXISTING dest nested a second copy at
    dest/skill/skill; the manifest copy addresses each file, so it cannot."""
    skill = source / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("demo v1\n", encoding="utf-8")
    (skill / "notes.md").write_text("notes v1\n", encoding="utf-8")
    run(config, source, files=("skills/demo",))
    (config / "skills" / "demo" / "notes.md").write_text("my notes\n", encoding="utf-8")

    result = run(config, source, files=("skills/demo",))

    assert result.returncode == 0, result.stdout + result.stderr
    assert not (config / "skills" / "demo" / "demo").exists()
    assert (config / "skills" / "demo" / "notes.md").read_text(encoding="utf-8") == "my notes\n"
    assert "MODIFIED-BY-USER skills/demo/notes.md" in result.stdout, result.stdout
    assert "1 UNCHANGED" in result.stdout and "1 MODIFIED-BY-USER" in result.stdout


def test_empty_directory_is_rejected(config: Path, source: Path) -> None:
    (source / "skills" / "empty").mkdir(parents=True)

    result = run(config, source, files=("skills/empty",))

    assert result.returncode == 2
    assert "skills/empty" in result.stderr
    assert not (config / MANIFEST).exists()


def test_repeated_install_paths_are_counted_once(config: Path, source: Path) -> None:
    result = run(config, source, files=("rules/a.md", "rules/a.md", "rules"))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "1 NEW" in result.stdout, result.stdout
    assert set(manifest(config)["files"]) == {"rules/a.md"}


# ── install.sh optional installers go through the same classified copy ─────
#
# These drive the real install.sh against a PRIVATE copy of its inputs, so a test
# can change UPSTREAM (edit a hook in the checkout) without touching this tree.

def _scratch_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    shutil.copy2(ROOT / "install.sh", root / "install.sh")
    shutil.copytree(ROOT / "scripts", root / "scripts",
                    ignore=shutil.ignore_patterns("test_*", "__pycache__", "*.ps1", "runtime-qualification"))
    for component in ("profiles", "rules", "agents", "agent-memory"):
        shutil.copytree(ROOT / component, root / component, ignore=shutil.ignore_patterns("__pycache__"))
    (root / "hooks").mkdir()
    for path in (ROOT / "hooks").iterdir():
        if path.is_file():
            shutil.copy2(path, root / "hooks" / path.name)
    shutil.copytree(ROOT / "hooks" / "session_start_modules", root / "hooks" / "session_start_modules",
                    ignore=shutil.ignore_patterns("__pycache__"))
    # One tiny skill plus the shared assets keeps the skills menu real and fast.
    (root / "skills" / "demo").mkdir(parents=True)
    (root / "skills" / "demo" / "SKILL.md").write_text("---\nname: demo\n---\ndemo\n", encoding="utf-8")
    (root / "skills" / "_shared").mkdir()
    (root / "skills" / "_shared" / "conventions.md").write_text("shared\n", encoding="utf-8")
    return root


def _install(checkout: Path, home: Path, answers: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_CONFIG_DIR"] = str(home / ".claude")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [BASH, str(checkout / "install.sh")], input=answers, cwd=checkout, env=env,
        capture_output=True, text=True, encoding="utf-8", timeout=120, check=False)


# Answer prefixes: skip the settings profile, skip the starter core. The scratch
# checkout has no ARCHITECTURE.md or CLAUDE.template.md, so no prompt follows
# agent-memory.
SKIP_TO_COMPONENTS = "n\nn\n"


@pytestmark_bash
def test_install_sh_rules_menu_keeps_a_user_edit_on_reinstall(tmp_path: Path) -> None:
    checkout = _scratch_checkout(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    # all rules, skip skills, skip hooks, no agents, no agent-memory
    answers = SKIP_TO_COMPONENTS + "1\n8\n4\nn\nn\n"
    name = sorted(p.name for p in (checkout / "rules").glob("*.md"))[0]
    rule = home / ".claude" / "rules" / name

    first = _install(checkout, home, answers)
    assert first.returncode == 0, first.stdout + first.stderr
    assert f"rules/{name}" in manifest(home / ".claude")["files"]
    rule.write_text("my local edit\n", encoding="utf-8")

    second = _install(checkout, home, answers)
    assert second.returncode == 0, second.stdout + second.stderr
    assert rule.read_text(encoding="utf-8") == "my local edit\n"
    assert f"MODIFIED-BY-USER rules/{name}" in second.stdout, second.stdout
    assert not rule.with_name(rule.name + ".harness-new").exists()


@pytestmark_bash
def test_install_sh_hooks_menu_upgrades_an_untouched_hook(tmp_path: Path) -> None:
    checkout = _scratch_checkout(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    # skip rules, skip skills, fresh-laptop hook bundle, wire, no agents, no agent-memory
    answers = SKIP_TO_COMPONENTS + "3\n8\n1\ny\nn\nn\n"
    installed = home / ".claude" / "hooks" / "config-guard.py"
    upstream = checkout / "hooks" / "config-guard.py"

    first = _install(checkout, home, answers)
    assert first.returncode == 0, first.stdout + first.stderr
    v1 = installed.read_bytes()
    upstream.write_bytes(v1 + b"\n# upstream v2\n")

    second = _install(checkout, home, answers)
    assert second.returncode == 0, second.stdout + second.stderr
    assert installed.read_bytes() == v1 + b"\n# upstream v2\n"
    assert "CONFLICT" not in second.stdout and "MODIFIED-BY-USER" not in second.stdout, second.stdout
    assert not installed.with_name(installed.name + ".harness-new").exists()


@pytestmark_bash
def test_install_sh_hooks_menu_both_changed_leaves_harness_new(tmp_path: Path) -> None:
    checkout = _scratch_checkout(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    answers = SKIP_TO_COMPONENTS + "3\n8\n1\ny\nn\nn\n"
    installed = home / ".claude" / "hooks" / "config-guard.py"
    upstream = checkout / "hooks" / "config-guard.py"

    first = _install(checkout, home, answers)
    assert first.returncode == 0, first.stdout + first.stderr
    v1 = installed.read_bytes()
    installed.write_bytes(v1 + b"\n# my edit\n")
    upstream.write_bytes(v1 + b"\n# upstream v2\n")

    second = _install(checkout, home, answers)
    assert second.returncode == 0, second.stdout + second.stderr
    assert installed.read_bytes() == v1 + b"\n# my edit\n"
    assert installed.with_name("config-guard.py.harness-new").read_bytes() == v1 + b"\n# upstream v2\n"
    assert "CONFLICT hooks/config-guard.py" in second.stdout, second.stdout
    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    wired = {h["args"][0] for groups in settings["hooks"].values() for g in groups for h in g["hooks"]}
    assert "config-guard.py" in wired, "a kept file is still present, so it is still wired"


@pytestmark_bash
def test_install_sh_skills_agents_and_memory_are_recorded_and_reinstall_flat(tmp_path: Path) -> None:
    checkout = _scratch_checkout(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    # skip rules, pick skills individually -> demo yes, skip hooks, agents, agent-memory
    answers = SKIP_TO_COMPONENTS + "3\n7\ny\n4\ny\ny\n"
    agent = sorted(p.name for p in (checkout / "agents").glob("*.md"))[0]

    first = _install(checkout, home, answers)
    assert first.returncode == 0, first.stdout + first.stderr
    files = manifest(home / ".claude")["files"]
    assert {"skills/demo/SKILL.md", "skills/_shared/conventions.md",
            f"agents/{agent}", "agent-memory/README.md"} <= set(files), sorted(files)

    second = _install(checkout, home, answers)
    assert second.returncode == 0, second.stdout + second.stderr
    assert not (home / ".claude" / "skills" / "demo" / "demo").exists(), "cp -r used to nest a second copy here"
    assert "CONFLICT" not in second.stdout
    assert "NEW" not in second.stdout.replace(".harness-new", ""), second.stdout

