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

settings.json is never hash-classified; it keeps the union merge.
"""
from __future__ import annotations

import hashlib
import json
import os
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


def test_install_sh_starter_kit_uses_the_classified_copy() -> None:
    src = INSTALL_SH.read_text(encoding="utf-8")
    assert 'cp "$SCRIPT_DIR/rules/$rule" "$CLAUDE_DIR/rules/$rule"' not in src
    assert 'cp "$SCRIPT_DIR/hooks/$hook" "$CLAUDE_DIR/hooks/$hook"' not in src
    assert 'install_args+=(--install "$f")' in src
    assert 'for f in "${starter_files[@]}"' in src, "the copy must feed from the shared manifest"


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
