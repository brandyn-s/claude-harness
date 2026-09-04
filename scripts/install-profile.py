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
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
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
            found = [p for p in sorted(source.rglob("*"))
                     if p.is_file() and "__pycache__" not in p.relative_to(source).parts]
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
