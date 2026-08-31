#!/usr/bin/env python3
"""Check or repair Codex installed-skill copies from canonical source."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_ROOT = REPO_ROOT / "skills"
DEFAULT_TARGET_ROOT = Path.home() / ".agents" / "skills"
SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
SHARED_FILE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*\.md$")
IGNORED_PARTS = {
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".DS_Store",
}
CACHE_PATTERNS = (*IGNORED_PARTS, "*.pyc")


class SyncUnit(NamedTuple):
    """One named path in a single deployment transaction."""

    label: str
    source: Path
    target: Path


def _ignored(path: Path) -> bool:
    return any(part in IGNORED_PARTS for part in path.parts) or path.suffix == ".pyc"


def _entry_manifest(path: Path) -> tuple[str, str, int]:
    """Return kind, content/link target, and exact permission mode."""

    mode = stat.S_IMODE(path.lstat().st_mode)
    if path.is_symlink():
        return ("link", os.readlink(path), mode)
    if path.is_dir():
        return ("dir", "", mode)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return ("file", digest, mode)


def _tree_manifest(root: Path) -> dict[str, tuple[str, str, int]]:
    """Return an exact, cache-free recursive manifest."""
    if not root.is_dir():
        return {}

    manifest: dict[str, tuple[str, str, int]] = {".": _entry_manifest(root)}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if _ignored(relative):
            continue
        manifest[relative.as_posix()] = _entry_manifest(path)
    return manifest


def _path_manifest(path: Path) -> dict[str, tuple[str, str, int]]:
    """Manifest either a skill directory or one explicit shared file."""

    if not path.exists() and not path.is_symlink():
        return {}
    if path.is_dir() and not path.is_symlink():
        return _tree_manifest(path)
    return {".": _entry_manifest(path)}


def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _copy_to_stage(source: Path, staged: Path) -> None:
    """Copy a unit without generated caches while preserving modes."""

    if source.is_symlink():
        staged.symlink_to(os.readlink(source), target_is_directory=source.is_dir())
    elif source.is_dir():
        shutil.copytree(
            source,
            staged,
            symlinks=True,
            ignore=shutil.ignore_patterns(*CACHE_PATTERNS),
        )
    else:
        staged.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, staged, follow_symlinks=False)


def _mkdir_with_tracking(path: Path, created: list[Path]) -> None:
    missing: list[Path] = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    for directory in reversed(missing):
        directory.mkdir()
        created.append(directory)


def _rollback_promotions(records: list[dict[str, object]]) -> list[str]:
    errors: list[str] = []
    for record in reversed(records):
        target = record["target"]
        backup = record["backup"]
        try:
            if record["promoted"]:
                _remove_path(target)
            if record["had_target"] and (backup.exists() or backup.is_symlink()):
                os.replace(backup, target)
        except OSError as exc:  # pragma: no cover - catastrophic recovery path
            errors.append(f"{target}: {exc}")
    return errors


def _replace_group(units: list[SyncUnit], transaction_parent: Path) -> None:
    """Stage and promote all stale units, rolling back the group on failure."""

    transaction_parent.mkdir(parents=True, exist_ok=True)
    transaction = Path(
        tempfile.mkdtemp(prefix=".codex-skills-sync-", dir=transaction_parent)
    )
    staged_root = transaction / "staged"
    backup_root = transaction / "backups"
    staged_root.mkdir()
    backup_root.mkdir()
    staged_units: list[tuple[SyncUnit, Path]] = []
    records: list[dict[str, object]] = []
    created_dirs: list[Path] = []

    try:
        for index, unit in enumerate(units):
            staged = staged_root / f"{index:04d}-{unit.target.name}"
            _copy_to_stage(unit.source, staged)
            if _path_manifest(unit.source) != _path_manifest(staged):
                raise RuntimeError(f"staging parity verification failed: {unit.label}")
            staged_units.append((unit, staged))

        for index, (unit, staged) in enumerate(staged_units):
            _mkdir_with_tracking(unit.target.parent, created_dirs)
            backup = backup_root / f"{index:04d}-{unit.target.name}"
            had_target = unit.target.exists() or unit.target.is_symlink()
            record: dict[str, object] = {
                "target": unit.target,
                "backup": backup,
                "had_target": had_target,
                "promoted": False,
            }
            if had_target:
                os.replace(unit.target, backup)
            records.append(record)
            os.replace(staged, unit.target)
            record["promoted"] = True

        for unit in units:
            if _path_manifest(unit.source) != _path_manifest(unit.target):
                raise RuntimeError(
                    f"parity verification failed after group sync: {unit.label}"
                )
    except Exception as exc:
        rollback_errors = _rollback_promotions(records)
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass
        if rollback_errors:
            location = str(transaction)
            details = "; ".join(rollback_errors)
            raise RuntimeError(
                f"sync transaction failed: {exc}; rollback failed: {details}; "
                f"backups retained at {location}"
            ) from exc
        try:
            _remove_path(transaction)
        except OSError as cleanup_error:
            raise RuntimeError(
                f"sync transaction failed and rolled back: {exc}; "
                f"staging cleanup failed at {transaction}: {cleanup_error}"
            ) from exc
        raise RuntimeError(f"sync transaction failed and rolled back: {exc}") from exc
    else:
        _remove_path(transaction)


def _dependency_closure(source_root: Path, requested: list[str]) -> list[str]:
    """Return requested skills plus manifest dependencies in dependency-first order."""
    state: dict[str, str] = {}
    ordered: list[str] = []

    def visit(name: str, trail: tuple[str, ...]) -> None:
        if not SKILL_NAME.fullmatch(name):
            raise ValueError(f"invalid skill name: {name}")
        if state.get(name) == "done":
            return
        if state.get(name) == "visiting":
            cycle = " -> ".join((*trail, name))
            raise ValueError(f"requires_skills cycle: {cycle}")

        source = source_root / name
        manifest_path = source / "manifest.yaml"
        if not (source / "SKILL.md").is_file():
            raise ValueError(f"source skill missing SKILL.md: {source}")
        if not manifest_path.is_file():
            raise ValueError(
                f"cannot expand dependencies; manifest missing: {manifest_path}"
            )

        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid manifest YAML: {manifest_path}: {exc}") from exc
        dependencies = manifest.get("requires_skills", [])
        if dependencies is None:
            dependencies = []
        if not isinstance(dependencies, list) or not all(
            isinstance(dependency, str) for dependency in dependencies
        ):
            raise ValueError(
                f"requires_skills must be a list of names: {manifest_path}"
            )

        state[name] = "visiting"
        for dependency in dependencies:
            visit(dependency, (*trail, name))
        state[name] = "done"
        ordered.append(name)

    for name in requested:
        visit(name, ())
    return ordered


def _sync_units(
    source_root: Path,
    target_root: Path,
    names: list[str],
    shared_files: list[str],
) -> list[SyncUnit]:
    """Validate and resolve every unit before any target write."""

    units: list[SyncUnit] = []
    for name in names:
        if not SKILL_NAME.fullmatch(name):
            raise ValueError(f"invalid skill name: {name}")
        source = source_root / name
        if not (source / "SKILL.md").is_file():
            raise ValueError(f"source skill missing SKILL.md: {source}")
        units.append(SyncUnit(name, source, target_root / name))

    source_shared = source_root / "_shared"
    target_shared = target_root / "_shared"
    if shared_files and source_shared.is_symlink():
        raise ValueError(
            f"source shared directory must not be a symlink: {source_shared}"
        )
    if shared_files and target_shared.is_symlink():
        raise ValueError(
            f"target shared directory must not be a symlink: {target_shared}"
        )
    for name in dict.fromkeys(shared_files):
        if not SHARED_FILE_NAME.fullmatch(name):
            raise ValueError(f"invalid shared file name: {name}")
        source = source_shared / name
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"source shared file missing or unsafe: {source}")
        units.append(SyncUnit(f"shared:{name}", source, target_shared / name))
    return units


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check or repair selected $HOME/.agents/skills copies from this "
            "repository's canonical skills/ directories."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check", action="store_true", help="report drift without writing"
    )
    mode.add_argument(
        "--apply", action="store_true", help="replace only named stale copies"
    )
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--target-root", type=Path, default=DEFAULT_TARGET_ROOT)
    parser.add_argument(
        "--with-dependencies",
        action="store_true",
        help=(
            "recursively include each named skill's requires_skills closure "
            "from manifest.yaml"
        ),
    )
    parser.add_argument(
        "--shared-file",
        action="append",
        default=[],
        metavar="NAME.md",
        help=(
            "include one basename-only Markdown file from skills/_shared; "
            "repeat for multiple files and promote them with the named skills"
        ),
    )
    parser.add_argument(
        "skills", nargs="+", help="skill names, for example: retro distill ship"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    drift = False
    source_root = args.source_root.expanduser().resolve()
    target_root = args.target_root.expanduser().resolve()

    try:
        names = (
            _dependency_closure(source_root, args.skills)
            if args.with_dependencies
            else list(dict.fromkeys(args.skills))
        )
        units = _sync_units(source_root, target_root, names, args.shared_file)
    except ValueError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2

    statuses = [
        (unit, _path_manifest(unit.source) == _path_manifest(unit.target))
        for unit in units
    ]
    if args.check:
        for unit, in_sync in statuses:
            print(f"{'OK' if in_sync else 'DRIFT'} {unit.label}")
            drift = drift or not in_sync
        return 1 if drift else 0

    stale = [unit for unit, in_sync in statuses if not in_sync]
    if stale:
        try:
            _replace_group(stale, target_root.parent)
        except (OSError, RuntimeError) as exc:
            print(f"ERROR {exc}", file=sys.stderr)
            return 2
    for unit, in_sync in statuses:
        print(f"{'OK' if in_sync else 'SYNCED'} {unit.label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
