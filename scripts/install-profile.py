#!/usr/bin/env python3
"""Preview or apply a portable Claude Code settings profile safely.

`--profile` merges a settings overlay into the target settings.json (permission
lists union, other keys replace). `--install <repo-relative path>` copies a
repository file -- or every regular file beneath a directory, `__pycache__`
skipped -- into the config root (the directory holding the target) and records
each file's sha256 in <config_root>/.harness-install-state.json, so a later run
can tell an untouched copy from your edit:

    NEW               target absent                                -> written
    UNCHANGED         target == recorded hash (or == new content)  -> written
    MODIFIED-BY-USER  you edited it; upstream did not change       -> kept, reported
    CONFLICT          both changed                                 -> kept, new version
                                                                      beside it as
                                                                      <name>.harness-new
A file with no record (installed before the manifest existed) is UNCHANGED when
it equals the new content and CONFLICT otherwise. `--force` writes everything.
settings.json is never hash-classified; it keeps the merge.

A Python target under hooks/ (or bin/, scripts/) brings its local dependencies
along, transitively: every sibling module or package it imports (found by
parsing it, module level or nested) and every checkout file its
hooks/manifests/<name>.yaml lists under `depends_on_files`. Each addition is
printed once -- `also installing hooks/_environment_catalog.py (imported by
hooks/bash-security-guard.py)` -- in preview and --apply alike, and is
classified and recorded exactly like an explicit target. A name with no
sibling file is stdlib or third-party and is ignored. 2026-09-04: without
this, `--install hooks/bash-security-guard.py --apply` upgraded the guard but
not the _environment_catalog module it had started importing; the installed
guard crashed on import and the fail-closed Bash dispatcher blocked every
command until the module was copied in by hand.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles"
STATE_NAME = ".harness-install-state.json"
STATUSES = ("NEW", "UNCHANGED", "MODIFIED-BY-USER", "CONFLICT")


def _object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


# Permission rule lists UNION with what is already installed. Replacing them
# silently discarded a user's own decisions: measured 2026-09-03, applying
# fresh-laptop over a curated settings.json cut permissions.allow from 34 to 3.
# Other profile-owned lists (e.g. enabledMcpjsonServers) still replace.
_APPEND_LISTS = {
    ("permissions", "allow"),
    ("permissions", "deny"),
    ("permissions", "ask"),
    ("autoMode", "environment"),
    ("autoMode", "allow"),
    ("autoMode", "soft_deny"),
    ("autoMode", "hard_deny"),
}


def merge(
    base: dict[str, Any],
    overlay: dict[str, Any],
    path: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Recursively merge objects; permission lists append + dedupe, other lists replace."""
    result = dict(base)
    for key, value in overlay.items():
        child_path = (*path, key)
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value, child_path)
        elif child_path in _APPEND_LISTS and isinstance(value, list):
            existing = result.get(key, [])
            if not isinstance(existing, list):
                existing = []
            result[key] = list(dict.fromkeys([*existing, *value]))
        else:
            result[key] = value
    return result


def _backup_path(target: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    candidate = target.with_name(f"{target.name}.bak.{stamp}")
    index = 1
    while candidate.exists():
        candidate = target.with_name(f"{target.name}.bak.{stamp}.{index}")
        index += 1
    return candidate


def _atomic_write_bytes(target: Path, data: bytes, mode: int | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _atomic_write(target: Path, value: dict[str, Any]) -> None:
    text = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    _atomic_write_bytes(target, text.encode("utf-8"))


# ── install state ────────────────────────────────────────────────────────


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_state(config_root: Path) -> dict[str, Any]:
    path = config_root / STATE_NAME
    try:
        files = _object(path).get("files")
    except ValueError as exc:
        # Unreadable state cannot be trusted either way; with no records every
        # differing file classifies as CONFLICT, which keeps the user's copy.
        print(f"warning: {path} is unreadable ({exc}); treating every file as unrecorded")
        files = None
    return {"version": 1, "files": files if isinstance(files, dict) else {}}


def classify(dest: Path, new_sha: str, recorded: str | None) -> str:
    if not dest.exists():
        return "NEW"
    current = _sha256(dest.read_bytes())
    if current in (new_sha, recorded):
        return "UNCHANGED"
    if new_sha == recorded:
        return "MODIFIED-BY-USER"
    return "CONFLICT"


def install_files(
    source_root: Path,
    config_root: Path,
    rel_paths: list[str],
    *,
    profiles: list[str],
    apply: bool,
    force: bool,
) -> None:
    state = load_state(config_root)
    records: dict[str, Any] = state["files"]
    now = datetime.now(UTC).isoformat(timespec="seconds")
    counts: Counter[str] = Counter()
    kept: list[str] = []
    for rel in rel_paths:
        src = source_root / rel
        dest = config_root / rel
        new = src.read_bytes()
        new_sha = _sha256(new)
        record = records.get(rel)
        recorded = record.get("sha256") if isinstance(record, dict) else None
        status = classify(dest, new_sha, recorded)
        counts[status] += 1
        write = force or status in ("NEW", "UNCHANGED")
        if not write:
            detail = ("your edits kept (--force overwrites)" if status == "MODIFIED-BY-USER"
                      else f"your edits kept; upstream version beside it as {rel}.harness-new")
            kept.append(f"  {status} {rel}: {detail}")
        if not apply:
            continue
        if write:
            _atomic_write_bytes(dest, new, mode=src.stat().st_mode & 0o777)
            records[rel] = {"sha256": new_sha, "profiles": profiles, "installed_at": now}
        elif status == "CONFLICT":
            _atomic_write_bytes(dest.with_name(dest.name + ".harness-new"), new)
    if apply:
        _atomic_write(config_root / STATE_NAME, state)
    summary = ", ".join(f"{counts[s]} {s}" for s in STATUSES if counts[s])
    forced = f"; all {len(rel_paths)} written (--force)" if force else ""
    print(f"install state: {summary}{forced}")
    for line in kept:
        print(line)


# ── local dependencies of --install targets ──────────────────────────────
#
# 2026-09-04: `--install hooks/bash-security-guard.py --apply` upgraded the guard
# alone. The new guard imports the sibling module _environment_catalog, which the
# older install had never received, so the installed guard crashed on import and
# hooks/bash-pretooluse-dispatcher.py -- fail-closed on a crashed guard, as a
# guard dispatcher must be -- blocked every Bash command until the module was
# copied in by hand. A targeted install therefore brings what the file imports
# and what its manifest declares, transitively, and treats each addition like a
# target. Everything here is static: no hook code runs.

_GLOB_CHARS = frozenset("*?[")


def _files_beneath(directory: Path) -> list[Path]:
    """Every regular file beneath `directory`, sorted, `__pycache__` skipped."""
    return [p for p in sorted(directory.rglob("*"))
            if p.is_file() and "__pycache__" not in p.relative_to(directory).parts]


def _yaml_scalar(text: str) -> str:
    """One flow scalar as the manifests write them: bare or quoted, trailing comment dropped."""
    text = text.strip()
    if text.startswith("#"):
        return ""
    if text[:1] in ("'", '"'):
        end = text.find(text[0], 1)
        if end > 0:
            return text[1:end]
    return text.split(" #", 1)[0].rstrip()


def manifest_dependencies(manifest: Path) -> list[str]:
    """The `depends_on_files` entries of a hook manifest, read with the stdlib only.

    The installer runs on a fresh laptop before PyYAML exists, so this reads
    just the one key it needs: an inline `depends_on_files: [a, b]` or a
    `- item` block. Anything else under the key (null, a scalar) is no
    dependencies. scripts/test_install_profile.py proves parity with PyYAML
    over every committed manifest.
    """
    key = "depends_on_files:"
    entries: list[str] = []
    in_block = False
    for raw in manifest.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if in_block:
            if stripped.startswith("- "):
                entries.append(_yaml_scalar(stripped[2:]))
            elif stripped and not stripped.startswith("#"):
                break
            continue
        if raw.startswith(key):
            rest = _yaml_scalar(raw[len(key):])
            if rest.startswith("[") and rest.endswith("]"):
                return [_yaml_scalar(part) for part in rest[1:-1].split(",") if part.strip()]
            if rest:
                return []
            in_block = True
    return entries


def _imported_names(source: Path) -> list[str]:
    """Top-level names a Python file imports, at module level or nested."""
    try:
        tree = ast.parse(source.read_bytes(), filename=str(source))
    except (SyntaxError, ValueError) as exc:
        print(f"warning: {source} does not parse ({exc}); its imports were not followed")
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.append(node.module.split(".")[0])
    return list(dict.fromkeys(names))


def _resolve_import(source_root: Path, importer: str, name: str) -> list[str]:
    """Checkout files a top-level imported name maps to for `importer`, or [].

    Looked up as <dir>/<name>.py or the package <dir>/<name>/__init__.py, first
    in the importer's own directory, then in its component root (hooks/, bin/,
    scripts/) -- the directory the hooks put on sys.path themselves. A package
    is taken whole. A name with no such file is stdlib or third-party.
    """
    path = Path(importer)
    roots = [path.parent]
    if len(path.parts) > 1:
        roots.append(Path(path.parts[0]))
    for directory in dict.fromkeys(roots):
        module = source_root / directory / f"{name}.py"
        if module.is_file():
            return [module.relative_to(source_root).as_posix()]
        package = source_root / directory / name
        if (package / "__init__.py").is_file():
            return [p.relative_to(source_root).as_posix() for p in _files_beneath(package)]
    return []


def _manifest_for(source_root: Path, rel: str) -> Path | None:
    """hooks/manifests/<stem>.yaml for a file directly under hooks/, when it exists."""
    path = Path(rel)
    if len(path.parts) == 2 and path.parts[0] == "hooks":
        manifest = source_root / "hooks" / "manifests" / f"{path.stem}.yaml"
        if manifest.is_file():
            return manifest
    return None


def _resolve_declared(source_root: Path, entry: str) -> list[str]:
    """Checkout files a manifest `depends_on_files` entry names, or [].

    The manifests spell entries repo-relative (contracts/environment-catalog.json),
    hooks-relative (bash_policy_tables.py) or as a glob
    (hooks/session_start_modules/*.py); a directory means every file beneath it.
    Runtime paths (~/.claude/settings.json), prose and anything that would
    escape the checkout name nothing in it and resolve to [].
    """
    path = Path(entry)
    if not entry or path.is_absolute() or entry.startswith("~") or ".." in path.parts:
        return []
    for base in (source_root, source_root / "hooks"):
        if _GLOB_CHARS & set(entry):
            try:
                found = sorted(p for p in base.glob(entry) if p.is_file())
            except (ValueError, NotImplementedError):
                found = []
        elif (base / path).is_file():
            found = [base / path]
        elif (base / path).is_dir():
            found = _files_beneath(base / path)
        else:
            found = []
        if found:
            return [p.relative_to(source_root).as_posix() for p in found]
    return []


def dependency_closure(source_root: Path, rel_paths: list[str]) -> list[tuple[str, str]]:
    """Local dependencies of `rel_paths` not already among them, transitively.

    Returns (repo-relative path, reason) pairs in discovery order, each path
    once. Two static sources feed it: the imports of every Python file (see
    _resolve_import) and the `depends_on_files` of a hook's manifest (see
    _resolve_declared); every addition is scanned in turn. Not followed:
    imports that rely on a sys.path insert into another component (bin/ ->
    scripts/), which only the installed file itself could express.
    """
    seen = dict.fromkeys(rel_paths)
    additions: list[tuple[str, str]] = []
    queue = deque(rel_paths)
    while queue:
        rel = queue.popleft()
        found: list[tuple[str, str]] = []
        if rel.endswith(".py"):
            for name in _imported_names(source_root / rel):
                found.extend((dep, f"imported by {rel}") for dep in _resolve_import(source_root, rel, name))
        manifest = _manifest_for(source_root, rel)
        if manifest is not None:
            reason = f"declared by {manifest.relative_to(source_root).as_posix()}"
            for entry in manifest_dependencies(manifest):
                found.extend((dep, reason) for dep in _resolve_declared(source_root, entry))
        for dep, reason in found:
            if dep not in seen:
                seen[dep] = None
                additions.append((dep, reason))
                queue.append(dep)
    return additions


# ── cli ──────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--profile",
        dest="profiles",
        action="append",
        help="profile overlay to apply; repeat in base-to-specialized order "
        "(default fresh-laptop, unless --install is given)",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.home() / ".claude" / "settings.json",
        help="settings.json to merge into; its directory is the config root",
    )
    parser.add_argument(
        "--install",
        action="append",
        default=[],
        metavar="PATH",
        help="repo-relative file, or directory of files, to copy into the config "
        "root with hash classification; repeatable",
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=ROOT,
        help="checkout to copy --install files from (default: this checkout)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="write every --install target regardless of classification",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the merged settings; without this flag the command is read-only",
    )
    args = parser.parse_args()

    profile_names = args.profiles or ([] if args.install else ["fresh-laptop"])
    profile_paths = [PROFILES / name / "settings.json" for name in profile_names]
    for name, profile_path in zip(profile_names, profile_paths, strict=True):
        if not profile_path.is_file():
            parser.error(f"unknown profile {name!r}: {profile_path} not found")
    if args.force and not args.install:
        parser.error("--force applies to --install targets")

    target = args.target.expanduser().resolve()
    config_root = target.parent
    source_root = args.source_root.expanduser().resolve()
    install: list[str] = []
    for rel in args.install:
        path = Path(rel)
        if path.is_absolute() or ".." in path.parts:
            parser.error(f"--install {rel}: must be a relative path inside the checkout")
        source = source_root / path
        if source.is_dir():
            found = _files_beneath(source)
            if not found:
                parser.error(f"--install {rel}: {source} contains no files")
            members = [p.relative_to(source_root).as_posix() for p in found]
        elif source.is_file():
            members = [path.as_posix()]
        else:
            parser.error(f"--install {rel}: {source} is not a file or directory")
        for member in members:
            if (config_root / member).resolve() == target:
                parser.error(f"--install {rel}: settings.json is merged from --profile, not copied")
            if member not in install:
                install.append(member)

    print("profiles: " + (" -> ".join(profile_names) or "(none)"))
    print(f"target: {target}")
    print(f"mode: {'apply' if args.apply else 'preview'}")

    changed = False
    merged: dict[str, Any] = {}
    if profile_names:
        current = _object(target)
        merged = current
        for profile in (_object(path) for path in profile_paths):
            merged = merge(merged, profile)
        changed = merged != current
        print(f"changed: {'yes' if changed else 'no'}")
        managed_keys = {key for path in profile_paths for key in _object(path)}
        print("managed keys: " + ", ".join(sorted(managed_keys)))

    for dep, reason in dependency_closure(source_root, install):
        if (config_root / dep).resolve() == target:
            print(f"skipping {dep} ({reason}): settings.json is merged from --profile, not copied")
            continue
        print(f"also installing {dep} ({reason})")
        install.append(dep)

    if not args.apply:
        if install:
            install_files(source_root, config_root, install,
                          profiles=profile_names, apply=False, force=args.force)
        print("No files written. Re-run with --apply after reviewing the profile.")
        return 0

    if profile_names and not changed:
        print("Target already matches the profile; settings.json not rewritten.")
    elif profile_names:
        if target.exists():
            backup = _backup_path(target)
            shutil.copy2(target, backup)
            print(f"backup: {backup}")
        _atomic_write(target, merged)
        print("Applied profile atomically.")
    if install:
        install_files(source_root, config_root, install,
                      profiles=profile_names, apply=True, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
