#!/usr/bin/env python3
"""Preview or apply a portable Claude Code settings profile safely."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ROOT / "profiles"


def _object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path}")
    return value


def merge(
    base: dict[str, Any],
    overlay: dict[str, Any],
    path: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Recursively merge objects; review boundaries append, other lists replace."""
    result = dict(base)
    for key, value in overlay.items():
        child_path = (*path, key)
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value, child_path)
        elif child_path == ("permissions", "ask") and isinstance(value, list):
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


def _atomic_write(target: Path, value: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        dest="profiles",
        action="append",
        help="profile overlay to apply; repeat in base-to-specialized order",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path.home() / ".claude" / "settings.json",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the merged settings; without this flag the command is read-only",
    )
    args = parser.parse_args()

    profile_names = args.profiles or ["fresh-laptop"]
    profile_paths = [PROFILES / name / "settings.json" for name in profile_names]
    for name, profile_path in zip(profile_names, profile_paths, strict=True):
        if not profile_path.is_file():
            parser.error(f"unknown profile {name!r}: {profile_path} not found")

    target = args.target.expanduser().resolve()
    current = _object(target)
    profiles = [_object(path) for path in profile_paths]
    merged = current
    for profile in profiles:
        merged = merge(merged, profile)
    changed = merged != current

    print("profiles: " + " -> ".join(profile_names))
    print(f"target: {target}")
    print(f"mode: {'apply' if args.apply else 'preview'}")
    print(f"changed: {'yes' if changed else 'no'}")
    managed_keys = {key for profile in profiles for key in profile}
    print("managed keys: " + ", ".join(sorted(managed_keys)))

    if not args.apply:
        print("No files written. Re-run with --apply after reviewing the profile.")
        return 0
    if not changed:
        print("Target already matches the profile; no files written.")
        return 0

    if target.exists():
        backup = _backup_path(target)
        shutil.copy2(target, backup)
        print(f"backup: {backup}")
    _atomic_write(target, merged)
    print("Applied profile atomically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
