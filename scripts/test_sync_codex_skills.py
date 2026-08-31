"""Acceptance tests for the Codex installed-skill parity command."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMAND = REPO_ROOT / "bin" / "sync-codex-skills.py"
README = REPO_ROOT / "README.md"
AUDIT_SKILL = REPO_ROOT / "skills" / "audit-skill" / "SKILL.md"

spec = importlib.util.spec_from_file_location("sync_codex_skills", COMMAND)
sync_codex_skills = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sync_codex_skills
spec.loader.exec_module(sync_codex_skills)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(COMMAND), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def _seed_gather_closure(tmp_path: Path) -> tuple[Path, Path]:
    source_root = tmp_path / "source" / "skills"
    target_root = tmp_path / ".agents" / "skills"
    source_skill = source_root / "gather-claude"
    target_skill = target_root / "gather-claude"
    source_shared = source_root / "_shared"
    target_shared = target_root / "_shared"
    (source_skill / "scripts").mkdir(parents=True)
    (target_skill / "scripts").mkdir(parents=True)
    source_shared.mkdir(parents=True)
    target_shared.mkdir(parents=True)

    (source_skill / "SKILL.md").write_text("canonical skill\n", encoding="utf-8")
    source_script = source_skill / "scripts" / "report_lifecycle.py"
    source_script.write_text("# canonical lifecycle\n", encoding="utf-8")
    source_script.chmod(0o755)
    (target_skill / "SKILL.md").write_text("stale skill\n", encoding="utf-8")
    (target_skill / "scripts" / "report_lifecycle.py").write_text(
        "# stale lifecycle\n", encoding="utf-8"
    )

    for name in ("gather-conventions.md", "project-dir.md"):
        source = source_shared / name
        target = target_shared / name
        source.write_text(f"canonical {name}\n", encoding="utf-8")
        source.chmod(0o640)
        target.write_text(f"stale {name}\n", encoding="utf-8")
        target.chmod(0o600)
    return source_root, target_root


def _file_snapshot(root: Path) -> dict[str, tuple[bytes, int, int]]:
    return {
        path.relative_to(root).as_posix(): (
            path.read_bytes(),
            path.stat().st_mode & 0o777,
            path.stat().st_mtime_ns,
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_apply_replaces_one_stale_skill_and_check_then_passes(tmp_path: Path) -> None:
    source_root = tmp_path / "source" / "skills"
    target_root = tmp_path / ".agents" / "skills"
    source_skill = source_root / "retro"
    target_skill = target_root / "retro"
    source_skill.mkdir(parents=True)
    target_skill.mkdir(parents=True)
    (source_skill / "SKILL.md").write_text("canonical\n", encoding="utf-8")
    (target_skill / "SKILL.md").write_text("stale\n", encoding="utf-8")
    (target_skill / "retired.txt").write_text("remove me\n", encoding="utf-8")

    check_before = _run(
        "--check",
        "--source-root",
        str(source_root),
        "--target-root",
        str(target_root),
        "retro",
    )
    assert check_before.returncode == 1
    assert "DRIFT retro" in check_before.stdout

    apply = _run(
        "--apply",
        "--source-root",
        str(source_root),
        "--target-root",
        str(target_root),
        "retro",
    )
    assert apply.returncode == 0, apply.stderr
    assert "SYNCED retro" in apply.stdout
    assert (target_skill / "SKILL.md").read_text(encoding="utf-8") == "canonical\n"
    assert not (target_skill / "retired.txt").exists()

    check_after = _run(
        "--check",
        "--source-root",
        str(source_root),
        "--target-root",
        str(target_root),
        "retro",
    )
    assert check_after.returncode == 0, check_after.stdout + check_after.stderr
    assert "OK retro" in check_after.stdout


def test_readme_documents_check_before_apply() -> None:
    text = README.read_text(encoding="utf-8")
    check = (
        "python3 bin/sync-codex-skills.py --check --with-dependencies "
        "retro distill ship"
    )
    apply = (
        "python3 bin/sync-codex-skills.py --apply --with-dependencies "
        "retro distill ship"
    )
    assert check in text
    assert apply in text
    assert text.index(check) < text.index(apply)


def test_readme_documents_full_gather_family_package_repair() -> None:
    text = README.read_text(encoding="utf-8")
    closure = (
        "--shared-file gather-conventions.md --shared-file project-dir.md "
        "gather-claude gather-vendor"
    )
    check = f"python3 bin/sync-codex-skills.py --check {closure}"
    apply = f"python3 bin/sync-codex-skills.py --apply {closure}"
    assert text.count(check) == 2
    assert apply in text
    assert text.index(check) < text.index(apply)
    assert text.index(apply) < text.rindex(check)
    assert "complete installed gather-family closure" in text
    assert "`gather-vendor` consumes the same authoritative" in text
    assert "cmp -s skills/_shared" not in text
    assert "direct shared lifecycle dependency" in text


def test_gather_runtime_documents_the_actual_codex_shared_path() -> None:
    text = (REPO_ROOT / "skills" / "gather-claude" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "~/.agents/skills/_shared/project-dir.md" in text
    assert "~/.claude/skills/_shared/project-dir.md" not in text


def test_apply_syncs_gather_and_both_shared_files_with_exact_modes(
    tmp_path: Path,
) -> None:
    source_root, target_root = _seed_gather_closure(tmp_path)
    unrelated = target_root / "unrelated" / "keep.txt"
    unrelated.parent.mkdir()
    unrelated.write_text("owner data\n", encoding="utf-8")
    unrelated.chmod(0o604)
    unrelated_before = (
        unrelated.read_bytes(),
        unrelated.stat().st_mode & 0o777,
        unrelated.stat().st_mtime_ns,
    )

    result = _run(
        "--apply",
        "--source-root",
        str(source_root),
        "--target-root",
        str(target_root),
        "--shared-file",
        "gather-conventions.md",
        "--shared-file",
        "project-dir.md",
        "gather-claude",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SYNCED gather-claude" in result.stdout
    assert "SYNCED shared:gather-conventions.md" in result.stdout
    assert "SYNCED shared:project-dir.md" in result.stdout
    for name in ("gather-conventions.md", "project-dir.md"):
        source = source_root / "_shared" / name
        target = target_root / "_shared" / name
        assert target.read_bytes() == source.read_bytes()
        assert target.stat().st_mode & 0o777 == source.stat().st_mode & 0o777
    assert (
        target_root / "gather-claude" / "scripts" / "report_lifecycle.py"
    ).stat().st_mode & 0o111
    assert (
        unrelated.read_bytes(),
        unrelated.stat().st_mode & 0o777,
        unrelated.stat().st_mtime_ns,
    ) == unrelated_before


def test_apply_syncs_both_gather_packages_and_shared_contract_as_one_closure(
    tmp_path: Path,
) -> None:
    source_root, target_root = _seed_gather_closure(tmp_path)
    source_vendor = source_root / "gather-vendor"
    target_vendor = target_root / "gather-vendor"
    source_vendor.mkdir()
    target_vendor.mkdir()
    (source_vendor / "SKILL.md").write_text(
        "canonical QUALIFY lifecycle\n", encoding="utf-8"
    )
    (target_vendor / "SKILL.md").write_text("stale TRIAL lifecycle\n", encoding="utf-8")

    result = _run(
        "--apply",
        "--source-root",
        str(source_root),
        "--target-root",
        str(target_root),
        "--shared-file",
        "gather-conventions.md",
        "--shared-file",
        "project-dir.md",
        "gather-claude",
        "gather-vendor",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SYNCED gather-claude" in result.stdout
    assert "SYNCED gather-vendor" in result.stdout
    assert "SYNCED shared:gather-conventions.md" in result.stdout
    assert "SYNCED shared:project-dir.md" in result.stdout
    assert _path_bytes(target_vendor) == _path_bytes(source_vendor)


def _path_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_check_reports_shared_drift_without_writing_any_target(tmp_path: Path) -> None:
    source_root, target_root = _seed_gather_closure(tmp_path)
    (target_root / "gather-claude" / "SKILL.md").write_text(
        "canonical skill\n", encoding="utf-8"
    )
    source_script = source_root / "gather-claude" / "scripts" / "report_lifecycle.py"
    target_script = target_root / "gather-claude" / "scripts" / "report_lifecycle.py"
    target_script.write_bytes(source_script.read_bytes())
    target_script.chmod(source_script.stat().st_mode & 0o777)
    project_source = source_root / "_shared" / "project-dir.md"
    project_target = target_root / "_shared" / "project-dir.md"
    project_target.write_bytes(project_source.read_bytes())
    project_target.chmod(project_source.stat().st_mode & 0o777)
    before = _file_snapshot(target_root)

    result = _run(
        "--check",
        "--source-root",
        str(source_root),
        "--target-root",
        str(target_root),
        "--shared-file",
        "gather-conventions.md",
        "--shared-file",
        "project-dir.md",
        "gather-claude",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "OK gather-claude" in result.stdout
    assert "DRIFT shared:gather-conventions.md" in result.stdout
    assert "OK shared:project-dir.md" in result.stdout
    assert _file_snapshot(target_root) == before
    assert not list(target_root.parent.glob(".codex-skills-sync-*"))


def test_shared_file_rejects_path_traversal_before_any_write(tmp_path: Path) -> None:
    source_root, target_root = _seed_gather_closure(tmp_path)
    before = _file_snapshot(target_root)

    result = _run(
        "--apply",
        "--source-root",
        str(source_root),
        "--target-root",
        str(target_root),
        "--shared-file",
        "../gather-conventions.md",
        "gather-claude",
    )
    assert result.returncode == 2
    assert "invalid shared file name" in result.stderr
    assert _file_snapshot(target_root) == before


def test_group_promotion_failure_rolls_back_every_unit(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    source_root, target_root = _seed_gather_closure(tmp_path)
    before = _file_snapshot(target_root)
    target_project = target_root / "_shared" / "project-dir.md"
    real_replace = os.replace
    injected = False

    def fail_second_shared_promotion(source, target):
        nonlocal injected
        source_path = Path(source)
        target_path = Path(target)
        if (
            not injected
            and target_path == target_project
            and "staged" in source_path.parts
        ):
            injected = True
            raise OSError("injected second shared promotion failure")
        return real_replace(source, target)

    monkeypatch.setattr(sync_codex_skills.os, "replace", fail_second_shared_promotion)
    result = sync_codex_skills.main(
        [
            "--apply",
            "--source-root",
            str(source_root),
            "--target-root",
            str(target_root),
            "--shared-file",
            "gather-conventions.md",
            "--shared-file",
            "project-dir.md",
            "gather-claude",
        ]
    )
    output = capsys.readouterr()
    assert injected
    assert result == 2
    assert "injected second shared promotion failure" in output.err
    assert "SYNCED" not in output.out
    assert _file_snapshot(target_root) == before
    assert not list(target_root.parent.glob(".codex-skills-sync-*"))


def test_check_kills_skill_only_gather_sync_mutation(tmp_path: Path) -> None:
    """The pre-fix skill-only deployment must remain observable as drift."""
    source_root, target_root = _seed_gather_closure(tmp_path)
    source_skill = source_root / "gather-claude"
    target_skill = target_root / "gather-claude"
    for source in source_skill.rglob("*"):
        if not source.is_file():
            continue
        target = target_skill / source.relative_to(source_skill)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        target.chmod(source.stat().st_mode & 0o777)

    result = _run(
        "--check",
        "--source-root",
        str(source_root),
        "--target-root",
        str(target_root),
        "--shared-file",
        "gather-conventions.md",
        "--shared-file",
        "project-dir.md",
        "gather-claude",
    )
    assert result.returncode == 1
    assert "OK gather-claude" in result.stdout
    assert result.stdout.count("DRIFT shared:") == 2


def test_apply_restores_nested_gather_claude_runtime_package(tmp_path: Path) -> None:
    source_root = tmp_path / "source" / "skills"
    target_root = tmp_path / ".agents" / "skills"
    source_skill = source_root / "gather-claude"
    target_skill = target_root / "gather-claude"
    (source_skill / "scripts").mkdir(parents=True)
    target_skill.mkdir(parents=True)
    (source_skill / "SKILL.md").write_text("canonical Claude\n", encoding="utf-8")
    (source_skill / "scripts" / "reconcile_watching.py").write_text(
        "# canonical watcher\n", encoding="utf-8"
    )
    (source_skill / "scripts" / "report_lifecycle.py").write_text(
        "# canonical lifecycle\n", encoding="utf-8"
    )
    (source_skill / ".pytest_cache").mkdir()
    (source_skill / ".pytest_cache" / "CACHEDIR.TAG").write_text(
        "ephemeral\n", encoding="utf-8"
    )
    (source_skill / "scripts" / "__pycache__").mkdir()
    (source_skill / "scripts" / "__pycache__" / "runtime.pyc").write_bytes(b"cache")
    (target_skill / "SKILL.md").write_text("stale gather-Codex\n", encoding="utf-8")

    applied = _run(
        "--apply",
        "--source-root",
        str(source_root),
        "--target-root",
        str(target_root),
        "gather-claude",
    )
    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert "SYNCED gather-claude" in applied.stdout
    assert (target_skill / "scripts" / "reconcile_watching.py").is_file()
    assert (target_skill / "scripts" / "report_lifecycle.py").is_file()
    assert not (target_skill / ".pytest_cache").exists()
    assert not (target_skill / "scripts" / "__pycache__").exists()

    verified = _run(
        "--check",
        "--source-root",
        str(source_root),
        "--target-root",
        str(target_root),
        "gather-claude",
    )
    assert verified.returncode == 0, verified.stdout + verified.stderr
    assert "OK gather-claude" in verified.stdout


def test_with_dependencies_repairs_the_transitive_runtime_closure(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source" / "skills"
    target_root = tmp_path / ".agents" / "skills"

    dependencies = {
        "retro": ["distill", "mega-distill"],
        "distill": ["ship-hook"],
        "mega-distill": [],
        "ship-hook": [],
    }
    for name, required in dependencies.items():
        source = source_root / name
        target = target_root / name
        source.mkdir(parents=True)
        target.mkdir(parents=True)
        (source / "SKILL.md").write_text(f"canonical {name}\n", encoding="utf-8")
        manifest = [f"id: {name}", "requires_skills:"]
        manifest.extend(f"  - {dependency}" for dependency in required)
        if not required:
            manifest[-1] = "requires_skills: []"
        (source / "manifest.yaml").write_text(
            "\n".join(manifest) + "\n", encoding="utf-8"
        )
        content = f"canonical {name}\n" if name == "retro" else f"stale {name}\n"
        (target / "SKILL.md").write_text(content, encoding="utf-8")
        if name == "retro":
            (target / "manifest.yaml").write_text(
                "\n".join(manifest) + "\n", encoding="utf-8"
            )

    check_before = _run(
        "--check",
        "--with-dependencies",
        "--source-root",
        str(source_root),
        "--target-root",
        str(target_root),
        "retro",
    )
    assert check_before.returncode == 1
    assert "DRIFT ship-hook" in check_before.stdout
    assert "DRIFT distill" in check_before.stdout
    assert "DRIFT mega-distill" in check_before.stdout
    assert "OK retro" in check_before.stdout
    assert check_before.stdout.index("DRIFT ship-hook") < check_before.stdout.index(
        "OK retro"
    )

    apply = _run(
        "--apply",
        "--with-dependencies",
        "--source-root",
        str(source_root),
        "--target-root",
        str(target_root),
        "retro",
    )
    assert apply.returncode == 0, apply.stdout + apply.stderr
    for name in dependencies:
        assert (target_root / name / "SKILL.md").read_text(encoding="utf-8") == (
            f"canonical {name}\n"
        )
        assert (target_root / name / "manifest.yaml").is_file()

    check_after = _run(
        "--check",
        "--with-dependencies",
        "--source-root",
        str(source_root),
        "--target-root",
        str(target_root),
        "retro",
    )
    assert check_after.returncode == 0, check_after.stdout + check_after.stderr


def test_audit_skill_checks_deployed_dependency_closure() -> None:
    text = AUDIT_SKILL.read_text(encoding="utf-8")
    assert "requires_skills" in text
    assert "--with-dependencies" in text
    assert "transitive runtime dependency closure" in text
