#!/usr/bin/env python3
"""One-command snapshot/rollback for the Claude configuration.

WHY THIS EXISTS
---------------
Phase 0 of the remediation requires a version-pinned known-good configuration and
a one-command rollback path BEFORE any behavioural change lands. Without it, every
later phase is an irreversible experiment on a live control plane.

WHAT IT PROTECTS
----------------
Config files that change agent behaviour and are cheap to copy: settings files,
the hook scripts they register, and the agent definitions. It deliberately does
NOT touch transcripts, memory, or knowledge-base content -- those are data, not
configuration, and a rollback must never rewrite the record of what happened.

SAFETY PROPERTIES
-----------------
* `snapshot` never overwrites an existing snapshot id.
* Snapshot stores, slots, directories, files, and cleanup are descriptor-relative;
  replacing a pathname during creation cannot redirect writes or cleanup.
* `restore` writes a PRE-RESTORE snapshot first, so a rollback is itself
  reversible. A rollback that cannot be undone is not a safety mechanism.
* `restore` refuses to run unless `--confirm` is passed, and prints the exact
  file-level diff summary it is about to apply.
* Catchable interruptions are recovered before they are re-raised. SIGKILL and
  power loss are not catchable; this tool has no durable transaction journal,
  so use the already-printed pre-restore Undo command for manual recovery.
* Existing live leaves are atomically displaced and then verified; new content
  is installed with no-replace links. This closes the pathname check/use gap,
  but cannot revoke a writable descriptor another process already holds or stop
  a write after the final verification. Quiesce concurrent config writers.
* Every snapshot records the git HEAD + dirty state of the source repo and a
  SHA-256 digest for each captured file, so "known good" is version- and
  content-pinned rather than a vibe.
* It does not run or record an effective-configuration probe; runtime acceptance
  evidence remains separate.
* Nothing here contacts the network or an external system.

Usage:
    python3 bin/config_rollback.py snapshot --id pre-phase1
    python3 bin/config_rollback.py list
    python3 bin/config_rollback.py diff --id pre-phase1
    python3 bin/config_rollback.py restore --id pre-phase1 --confirm
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
import sys
from typing import Literal, overload

HOME = os.path.expanduser("~")
DEFAULT_STORE = os.path.join(HOME, ".claude", "config-snapshots")
DEFAULT_STATE_FILE = os.path.join(HOME, ".claude.json")
GLOBAL_APP_STATE_LOGICAL = "global-app-state/claude.json"

#: External files use fixed logical names inside snapshots. Restoration resolves
#: only these exact keys; no ``..`` path ever escapes the configuration root.
EXTERNAL_FILE_TARGETS = {
    GLOBAL_APP_STATE_LOGICAL: "state_file",
}

#: Configuration surfaces worth snapshotting, relative to the config root.
#: Data (transcripts, memory, KB) is deliberately excluded.
PROTECTED = (
    "settings.json",
    "settings.local.json",
    "hooks",
    "agents",
)

#: Never copy these, even inside a protected directory.
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}
SNAPSHOT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def utc_stamp() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def snapshot_path(store: str, snapshot_id: str) -> str:
    """Resolve one flat, portable snapshot id beneath the canonical store."""

    if not isinstance(snapshot_id, str) or not SNAPSHOT_ID_RE.fullmatch(snapshot_id):
        raise ValueError("invalid snapshot id")
    store_root = os.path.realpath(os.path.abspath(store))
    destination = os.path.join(store_root, snapshot_id)
    try:
        contained = os.path.commonpath((store_root, destination)) == store_root
    except ValueError:
        contained = False
    if not contained:
        raise ValueError("invalid snapshot id")
    return destination


def unique_snapshot_id(store: str, base: str) -> str:
    """Return `base`, or `base-2`, `base-3`, … if it is already taken.

    WHY: pre-restore snapshot ids were second-resolution (`pre-restore-<UTC>`),
    so two restores inside the SAME SECOND collided. `cmd_snapshot` correctly
    refuses to overwrite an existing snapshot, so the second restore ABORTED --
    an availability bug in the one tool you need working when things are already
    going wrong. Deterministically reproduced 2026-07-26 by
    test_restore_is_itself_reversible.

    The no-overwrite guard is the safety property and is NOT relaxed; the id is
    made collision-free instead. A bounded loop (not a timestamp with more
    digits) because sub-second stamps only shrink the window rather than close
    it, and because `os.path.exists` is the actual authority here.
    """
    candidate = base
    n = 1
    while os.path.lexists(os.path.join(store, candidate)):
        n += 1
        candidate = f"{base}-{n}"
        if n > 1000:  # pathological; fall back to a distinct suffix
            return f"{base}-{os.getpid()}"
    return candidate


def _open_regular_no_follow(
    path: str, *, trusted_root: str | None = None
) -> tuple[int, os.stat_result]:
    """Open one regular file without following descendants below a trusted root."""

    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise OSError("secure no-follow source reads are unavailable")
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_BINARY", 0)
    parent_fd = None
    descriptor = None
    try:
        if trusted_root is None:
            raw_path = os.path.abspath(path)
            secure_path = os.path.join(
                os.path.realpath(os.path.dirname(raw_path)),
                os.path.basename(raw_path),
            )
            parent_fd, leaf = _open_parent_directory_no_follow(
                secure_path,
                create=False,
            )
        else:
            lexical_root = os.path.abspath(trusted_root)
            lexical_path = os.path.abspath(path)
            try:
                inside_root = (
                    os.path.commonpath((lexical_root, lexical_path)) == lexical_root
                )
            except ValueError:
                inside_root = False
            if not inside_root:
                raise OSError("source escapes trusted root")
            relative = os.path.relpath(lexical_path, lexical_root)
            components = [part for part in relative.split(os.path.sep) if part]
            if not components or any(part in {".", ".."} for part in components):
                raise OSError("unsafe source path")
            directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            parent_fd = os.open(
                os.path.realpath(lexical_root),
                directory_flags,
            )
            for component in components[:-1]:
                next_fd = os.open(
                    component,
                    directory_flags,
                    dir_fd=parent_fd,
                )
                os.close(parent_fd)
                parent_fd = next_fd
            leaf = components[-1]

        descriptor = os.open(leaf, flags, dir_fd=parent_fd)
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise OSError("source is not a regular file")
        return descriptor, opened_stat
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        raise
    finally:
        if parent_fd is not None:
            os.close(parent_fd)


def _copy_source_to_snapshot(
    source: str, target: str, *, trusted_root: str | None = None
) -> str:
    """Copy and hash bytes from one no-follow source descriptor."""

    source_fd, source_stat = _open_regular_no_follow(
        source,
        trusted_root=trusted_root,
    )
    try:
        return _copy_open_source_to_snapshot(source_fd, source_stat, target)
    finally:
        os.close(source_fd)


def _copy_open_source_to_snapshot(
    source_fd: int,
    source_stat: os.stat_result,
    target: str,
) -> str:
    """Copy one source descriptor through a no-follow target parent handle."""

    parent_fd, leaf = _open_parent_directory_no_follow(target, create=True)
    try:
        digest, _ = _copy_open_source_to_snapshot_at(
            source_fd,
            source_stat,
            parent_fd,
            leaf,
        )
        return digest
    finally:
        os.close(parent_fd)


def _copy_open_source_to_snapshot_at(
    source_fd: int,
    source_stat: os.stat_result,
    parent_fd: int,
    leaf: str,
) -> tuple[str, int]:
    """Copy one source into an exclusively-created leaf below ``parent_fd``."""

    target_fd = None
    try:
        target_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        target_flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
        target_fd = os.open(
            leaf,
            target_flags,
            stat.S_IMODE(source_stat.st_mode),
            dir_fd=parent_fd,
        )
        digest = hashlib.sha256()
        with os.fdopen(source_fd, "rb", closefd=False) as source_file, os.fdopen(
            target_fd, "wb", closefd=False
        ) as target_file:
            for chunk in iter(lambda: source_file.read(65536), b""):
                digest.update(chunk)
                target_file.write(chunk)
            target_file.flush()
        os.fsync(target_fd)
        os.fchmod(target_fd, stat.S_IMODE(source_stat.st_mode))
        expected_hash = digest.hexdigest()
        os.close(target_fd)
        target_fd = None

        verify_fd = os.open(
            leaf,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_BINARY", 0),
            dir_fd=parent_fd,
        )
        try:
            stored_stat = os.fstat(verify_fd)
            if not stat.S_ISREG(stored_stat.st_mode):
                raise OSError("stored snapshot is not a regular file")
            stored_hash = hashlib.sha256()
            with os.fdopen(verify_fd, "rb", closefd=False) as stored_file:
                for chunk in iter(lambda: stored_file.read(65536), b""):
                    stored_hash.update(chunk)
        finally:
            os.close(verify_fd)
        if stored_hash.hexdigest() != expected_hash:
            raise OSError("stored snapshot verification failed")
        return expected_hash, stored_stat.st_size
    except BaseException:
        try:
            os.unlink(leaf, dir_fd=parent_fd)
        except OSError:
            pass
        raise
    finally:
        if target_fd is not None:
            os.close(target_fd)


def _sha256_regular_no_follow(path: str, *, trusted_root: str) -> str:
    descriptor, _ = _open_regular_no_follow(path, trusted_root=trusted_root)
    try:
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "rb", closefd=False) as source_file:
            for chunk in iter(lambda: source_file.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _snapshot_components(relative_path: str) -> list[str]:
    """Return a portable, traversal-safe snapshot-relative path."""

    if not isinstance(relative_path, str) or not relative_path:
        raise OSError("unsafe snapshot path")
    normalized = relative_path.replace("\\", "/")
    components = normalized.split("/")
    if (
        normalized.startswith("/")
        or any(part in {"", ".", ".."} for part in components)
    ):
        raise OSError("unsafe snapshot path")
    return components


def _open_snapshot_file(files_fd: int, relative_path: str):
    """Open a regular snapshot file through an already-anchored files dirfd."""

    components = _snapshot_components(relative_path)
    directory_fd = os.dup(files_fd)
    descriptor = None
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        for component in components[:-1]:
            next_fd = os.open(
                component,
                directory_flags,
                dir_fd=directory_fd,
            )
            os.close(directory_fd)
            directory_fd = next_fd
        descriptor = os.open(
            components[-1],
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_BINARY", 0),
            dir_fd=directory_fd,
        )
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise OSError("snapshot source is not a regular file")
        return descriptor, opened_stat
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        raise
    finally:
        os.close(directory_fd)


def _sha256_open_file(descriptor: int) -> str:
    digest = hashlib.sha256()
    with os.fdopen(descriptor, "rb", closefd=False) as source_file:
        for chunk in iter(lambda: source_file.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _walk_snapshot_files(directory_fd: int, prefix: str = ""):
    """Enumerate a snapshot tree without resolving any pathname after open."""

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    for name in sorted(os.listdir(directory_fd)):
        if name in {".", ".."} or "/" in name or "\\" in name:
            raise OSError("unsafe snapshot entry")
        entry_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        relative = f"{prefix}/{name}" if prefix else name
        if stat.S_ISDIR(entry_stat.st_mode):
            child_fd = os.open(name, directory_flags, dir_fd=directory_fd)
            try:
                yield from _walk_snapshot_files(child_fd, relative)
            finally:
                os.close(child_fd)
        elif stat.S_ISREG(entry_stat.st_mode):
            yield relative
        else:
            raise OSError("snapshot contains an unsafe entry")


def _open_snapshot_view(store: str, snapshot_id: str):
    """Anchor the store, slot, and files directories for one restore plan."""

    destination = snapshot_path(store, snapshot_id)
    store_fd = slot_fd = files_fd = manifest_fd = None
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        store_fd, leaf = _open_parent_directory_no_follow(
            destination,
            create=False,
        )
        slot_fd = os.open(leaf, directory_flags, dir_fd=store_fd)
        files_fd = os.open("files", directory_flags, dir_fd=slot_fd)
        manifest_fd = os.open(
            "manifest.json",
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_BINARY", 0),
            dir_fd=slot_fd,
        )
        if not stat.S_ISREG(os.fstat(manifest_fd).st_mode):
            raise OSError("snapshot manifest is not a regular file")
        return {
            "store_fd": store_fd,
            "slot_fd": slot_fd,
            "files_fd": files_fd,
            "manifest_fd": manifest_fd,
        }
    except BaseException:
        for descriptor in (manifest_fd, files_fd, slot_fd, store_fd):
            if descriptor is not None:
                os.close(descriptor)
        raise


def _close_snapshot_view(view) -> None:
    if not view:
        return
    for key in ("manifest_fd", "files_fd", "slot_fd", "store_fd"):
        descriptor = view.get(key)
        if descriptor is not None:
            os.close(descriptor)
            view[key] = None


def _close_plan(plan) -> None:
    if plan is not None:
        _close_snapshot_view(plan.get("snapshot_view"))


def format_command(argv: list[str], *, platform: str | None = None) -> str:
    """Render an argv vector for the target platform's native shell."""

    if (platform or os.name) == "nt":
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)


def _canonical_cli_path(path: str) -> str:
    return os.path.realpath(os.path.abspath(os.fspath(path)))


def _undo_command(args, pre_id: str) -> list[str]:
    return [
        sys.executable,
        os.path.realpath(__file__),
        "restore",
        "--id",
        pre_id,
        "--confirm",
        "--store",
        _canonical_cli_path(args.store),
        "--root",
        _canonical_cli_path(args.root),
        "--state-file",
        _canonical_cli_path(getattr(args, "state_file", DEFAULT_STATE_FILE)),
        "--repo",
        _canonical_cli_path(args.repo),
    ]


def _print_undo(args, pre_id: str) -> None:
    print("Undo with:")
    print(f"  {format_command(_undo_command(args, pre_id))}")


def iter_files(root: str):
    """Yield (abs_path, rel_path) for every snapshot-eligible file under root."""
    for name in PROTECTED:
        src = os.path.join(root, name)
        if os.path.isfile(src):
            yield src, name
        elif os.path.isdir(src):
            for dirpath, dirnames, filenames in os.walk(src):
                dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
                for fn in filenames:
                    abspath = os.path.join(dirpath, fn)
                    yield abspath, os.path.relpath(abspath, root)


def iter_snapshot_files(root: str, state_file: str):
    """Yield config-root files plus explicitly mapped global app state."""
    yield from iter_files(root)
    if state_file and os.path.isfile(state_file):
        yield state_file, GLOBAL_APP_STATE_LOGICAL


def restore_destination(args, logical_path: str) -> str:
    """Resolve a snapshot key to an explicit, traversal-safe live target."""
    target_attr = EXTERNAL_FILE_TARGETS.get(logical_path)
    if target_attr:
        raw_target = os.path.abspath(getattr(args, target_attr, DEFAULT_STATE_FILE))
        # The CLI path is the trusted boundary.  Canonicalize its parent so
        # platform aliases such as macOS /tmp -> /private/tmp are accepted,
        # while retaining the leaf name so a leaf symlink is still detectable.
        return os.path.join(
            os.path.realpath(os.path.dirname(raw_target)),
            os.path.basename(raw_target),
        )
    if not isinstance(logical_path, str) or ".." in logical_path.replace(
        "\\", "/"
    ).split("/"):
        raise ValueError(f"unsafe snapshot path: {logical_path!r}")

    # Treat the user-selected configuration root as trusted, canonicalize it
    # once, then reject symlinks only in descendants beneath that boundary.
    root = os.path.realpath(os.path.abspath(args.root))
    destination = os.path.abspath(os.path.join(root, logical_path))
    try:
        inside_root = os.path.commonpath((root, destination)) == root
    except ValueError:
        inside_root = False
    if not inside_root:
        raise ValueError(f"unsafe snapshot path: {logical_path!r}")
    return destination


def _validate_destination_ancestors(destination: str) -> None:
    """Reject a destination whose existing parent chain contains a symlink.

    ``abspath``/``commonpath`` prove lexical containment only.  A path such as
    ``<root>/hooks/guard.py`` still escapes when ``hooks`` is replaced by a
    symlink.  Inspect every existing parent without following links; the write
    path repeats this guarantee with directory descriptors to close the race
    between validation and copy on platforms that provide ``openat``.
    """
    destination = os.path.abspath(destination)
    parent = os.path.dirname(destination)
    drive, tail = os.path.splitdrive(parent)
    current = drive + os.path.sep if drive else os.path.sep
    for component in (part for part in tail.split(os.path.sep) if part):
        current = os.path.join(current, component)
        try:
            component_stat = os.lstat(current)
        except FileNotFoundError:
            return
        if os.path.islink(current) or not stat.S_ISDIR(component_stat.st_mode):
            raise ValueError("unsafe restore destination parent")


def _supports_no_follow_directory_fds() -> bool:
    return (
        os.open in os.supports_dir_fd
        and os.listdir in os.supports_fd
        and os.mkdir in os.supports_dir_fd
        and os.stat in os.supports_dir_fd
        and os.stat in os.supports_follow_symlinks
        and os.unlink in os.supports_dir_fd
        and os.rmdir in os.supports_dir_fd
        and os.link in os.supports_dir_fd
        and os.link in os.supports_follow_symlinks
        and os.rename in os.supports_dir_fd
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
    )


@overload
def _open_parent_directory_no_follow(
    destination: str,
    *,
    create: bool,
    track_created: Literal[False] = False,
) -> tuple[int, str]: ...


@overload
def _open_parent_directory_no_follow(
    destination: str,
    *,
    create: bool,
    track_created: Literal[True],
) -> tuple[int, str, list[str]]: ...


@overload
def _open_parent_directory_no_follow(
    destination: str,
    *,
    create: bool,
    track_created: bool,
) -> tuple[int, str] | tuple[int, str, list[str]]: ...


def _open_parent_directory_no_follow(
    destination: str, *, create: bool, track_created: bool = False
):
    """Open and anchor a destination parent, returning ``(fd, leaf)``."""
    drive, tail = os.path.splitdrive(destination)
    if drive:
        raise OSError("secure restore is unavailable for drive-qualified paths")
    components = [part for part in tail.split(os.path.sep) if part]
    if not components:
        raise OSError("unsafe empty restore destination")

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory_fd = os.open(os.path.sep, directory_flags)
    current_path = os.path.sep
    created_dirs = []
    try:
        for component in components[:-1]:
            next_path = os.path.join(current_path, component)
            try:
                next_fd = os.open(
                    component,
                    directory_flags,
                    dir_fd=directory_fd,
                )
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, mode=0o700, dir_fd=directory_fd)
                created_dirs.append(next_path)
                next_fd = os.open(
                    component,
                    directory_flags,
                    dir_fd=directory_fd,
                )
            os.close(directory_fd)
            directory_fd = next_fd
            current_path = next_path
        if track_created:
            return directory_fd, components[-1], created_dirs
        return directory_fd, components[-1]
    except BaseException:
        os.close(directory_fd)
        # The handles needed to identify an ancestor may already be closed.
        # Leave an empty directory rather than path-delete a possible replacement.
        raise


def _transaction_leaf(leaf: str, purpose: str) -> str:
    return f".{leaf}.config-rollback-{purpose}-{os.getpid()}-{secrets.token_hex(8)}"


def _copy_fd_to_dir_temp(
    source_fd: int,
    source_stat: os.stat_result,
    parent_fd: int,
    temp_leaf: str,
    *,
    expected_hash: str | None = None,
) -> str:
    """Stage one fsynced file beside its destination and verify its stored bytes."""

    temp_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    temp_flags |= getattr(os, "O_BINARY", 0)
    temp_fd = os.open(
        temp_leaf,
        temp_flags,
        stat.S_IMODE(source_stat.st_mode),
        dir_fd=parent_fd,
    )
    try:
        digest = hashlib.sha256()
        with os.fdopen(source_fd, "rb", closefd=False) as source_file, os.fdopen(
            temp_fd, "wb", closefd=False
        ) as temp_file:
            for chunk in iter(lambda: source_file.read(65536), b""):
                digest.update(chunk)
                temp_file.write(chunk)
            temp_file.flush()
        os.fsync(temp_fd)
        os.fchmod(temp_fd, stat.S_IMODE(source_stat.st_mode))
        staged_hash = digest.hexdigest()
        if expected_hash is not None and staged_hash != expected_hash:
            raise OSError("staged source hash mismatch")
    except BaseException:
        os.close(temp_fd)
        try:
            os.unlink(temp_leaf, dir_fd=parent_fd)
        except OSError:
            pass
        raise
    os.close(temp_fd)

    verify_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_BINARY", 0)
    verify_fd = os.open(temp_leaf, verify_flags, dir_fd=parent_fd)
    try:
        verify_stat = os.fstat(verify_fd)
        if not stat.S_ISREG(verify_stat.st_mode):
            raise OSError("staged destination is not a regular file")
        stored_hash = hashlib.sha256()
        with os.fdopen(verify_fd, "rb", closefd=False) as staged_file:
            for chunk in iter(lambda: staged_file.read(65536), b""):
                stored_hash.update(chunk)
        if stored_hash.hexdigest() != staged_hash:
            raise OSError("stored restore staging verification failed")
    except BaseException:
        try:
            os.unlink(temp_leaf, dir_fd=parent_fd)
        except OSError:
            pass
        raise
    finally:
        os.close(verify_fd)
    return staged_hash


def _backup_live_leaf(entry: dict) -> None:
    parent_fd = entry["parent_fd"]
    leaf = entry["leaf"]
    try:
        live_fd = os.open(
            leaf,
            os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_BINARY", 0),
            dir_fd=parent_fd,
        )
    except FileNotFoundError:
        entry["existed"] = False
        entry["live_hash"] = None
        entry["live_identity"] = None
        return
    try:
        live_stat = os.fstat(live_fd)
        if not stat.S_ISREG(live_stat.st_mode):
            raise OSError("unsafe live restore target")
        entry["live_identity"] = (live_stat.st_dev, live_stat.st_ino)
        backup_leaf = _transaction_leaf(leaf, "backup")
        entry["live_hash"] = _copy_fd_to_dir_temp(
            live_fd,
            live_stat,
            parent_fd,
            backup_leaf,
        )
        entry["backup_leaf"] = backup_leaf
        entry["existed"] = True
    finally:
        os.close(live_fd)


def _verify_live_leaf_matches_baseline(
    entry: dict,
    expected_live_hash: str | None,
) -> None:
    """Compare staging-time bytes with the completed pre-restore snapshot."""

    if expected_live_hash is None:
        matches = not entry["existed"]
    else:
        matches = entry["existed"] and entry["live_hash"] == expected_live_hash
    if not matches:
        raise OSError("live restore target changed after pre-restore snapshot")


def _leaf_stat_no_follow(parent_fd: int, leaf: str) -> os.stat_result | None:
    try:
        return os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _stat_identity(value: os.stat_result | None):
    if value is None:
        return None
    return value.st_dev, value.st_ino


def _leaf_matches_identity(parent_fd: int, leaf: str, identity) -> bool:
    return identity is not None and _stat_identity(
        _leaf_stat_no_follow(parent_fd, leaf)
    ) == identity


def _sha256_leaf_no_follow(parent_fd: int, leaf: str) -> str:
    descriptor = os.open(
        leaf,
        os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_BINARY", 0),
        dir_fd=parent_fd,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("live restore target is not a regular file")
        return _sha256_open_file(descriptor)
    finally:
        os.close(descriptor)


def _link_no_replace(parent_fd: int, source_leaf: str, target_leaf: str) -> None:
    """Create ``target_leaf`` atomically, failing if any entry already exists."""

    os.link(
        source_leaf,
        target_leaf,
        src_dir_fd=parent_fd,
        dst_dir_fd=parent_fd,
        follow_symlinks=False,
    )


def _probe_no_replace_link(parent_fd: int, source_leaf: str) -> None:
    """Prove hard-link CAS works in this exact destination directory."""

    probe_leaf = _transaction_leaf(source_leaf, "link-probe")
    try:
        _link_no_replace(parent_fd, source_leaf, probe_leaf)
        source_stat = _leaf_stat_no_follow(parent_fd, source_leaf)
        probe_stat = _leaf_stat_no_follow(parent_fd, probe_leaf)
        if (
            source_stat is None
            or probe_stat is None
            or not _same_object(source_stat, probe_stat)
        ):
            raise OSError("destination hard-link probe did not preserve identity")
    finally:
        try:
            os.unlink(probe_leaf, dir_fd=parent_fd)
        except FileNotFoundError:
            pass


def _verify_displaced_live_leaf(entry: dict) -> None:
    """Validate the exact live object after atomically moving its pathname."""

    descriptor = os.open(
        entry["displaced_leaf"],
        os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_BINARY", 0),
        dir_fd=entry["parent_fd"],
    )
    try:
        opened_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or _stat_identity(opened_stat) != entry["live_identity"]
            or _sha256_open_file(descriptor) != entry["live_hash"]
        ):
            raise OSError("live restore target changed concurrently")
    finally:
        os.close(descriptor)


def _verify_committed_entry(entry: dict) -> None:
    """Verify the desired leaf state before transaction backups are discarded."""

    live_stat = _leaf_stat_no_follow(entry["parent_fd"], entry["leaf"])
    if entry["remove"]:
        if live_stat is not None:
            raise OSError("deleted restore target reappeared concurrently")
        return
    if (
        live_stat is None
        or not stat.S_ISREG(live_stat.st_mode)
        or _stat_identity(live_stat) != entry["stage_identity"]
    ):
        raise OSError("restored target changed concurrently")
    descriptor = os.open(
        entry["leaf"],
        os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_BINARY", 0),
        dir_fd=entry["parent_fd"],
    )
    try:
        if _sha256_open_file(descriptor) != entry["stage_hash"]:
            raise OSError("restored target changed concurrently")
    finally:
        os.close(descriptor)


def _prepare_write_entry(
    source_fd: int,
    source_stat: os.stat_result,
    expected_hash: str,
    destination: str,
    expected_live_hash: str | None,
) -> dict:
    parent_fd, leaf, created_dirs = _open_parent_directory_no_follow(
        destination,
        create=True,
        track_created=True,
    )
    entry = {
        "parent_fd": parent_fd,
        "leaf": leaf,
        "stage_leaf": None,
        "backup_leaf": None,
        "existed": False,
        "live_hash": None,
        "live_identity": None,
        "remove": False,
        "committed": False,
        "displaced_leaf": None,
        "stage_hash": expected_hash,
        "stage_identity": None,
        "recovery_claim_leaf": None,
        "preserve_recovery_artifacts": False,
        "created_dirs": created_dirs,
    }
    try:
        stage_leaf = _transaction_leaf(leaf, "stage")
        _copy_fd_to_dir_temp(
            source_fd,
            source_stat,
            parent_fd,
            stage_leaf,
            expected_hash=expected_hash,
        )
        entry["stage_leaf"] = stage_leaf
        entry["stage_identity"] = _stat_identity(
            os.stat(
                stage_leaf,
                dir_fd=parent_fd,
                follow_symlinks=False,
            )
        )
        _backup_live_leaf(entry)
        _verify_live_leaf_matches_baseline(entry, expected_live_hash)
        _probe_no_replace_link(parent_fd, stage_leaf)
        return entry
    except BaseException:
        _cleanup_staged_entry(entry)
        raise


def _prepare_remove_entry(
    destination: str,
    expected_live_hash: str | None,
) -> dict:
    parent_fd, leaf = _open_parent_directory_no_follow(destination, create=False)
    entry = {
        "parent_fd": parent_fd,
        "leaf": leaf,
        "stage_leaf": None,
        "backup_leaf": None,
        "existed": False,
        "live_hash": None,
        "live_identity": None,
        "remove": True,
        "committed": False,
        "displaced_leaf": None,
        "stage_hash": None,
        "stage_identity": None,
        "recovery_claim_leaf": None,
        "preserve_recovery_artifacts": False,
        "created_dirs": [],
    }
    try:
        _backup_live_leaf(entry)
        if not entry["existed"]:
            raise OSError("restore deletion target disappeared")
        _verify_live_leaf_matches_baseline(entry, expected_live_hash)
        _probe_no_replace_link(parent_fd, entry["backup_leaf"])
        return entry
    except BaseException:
        _cleanup_staged_entry(entry)
        raise


def _commit_staged_entry(entry: dict) -> None:
    """Claim the live name, validate it, then publish without replacement."""

    parent_fd = entry["parent_fd"]
    if entry["existed"]:
        displaced_leaf = _transaction_leaf(entry["leaf"], "displaced")
        entry["displaced_leaf"] = displaced_leaf
        os.rename(
            entry["leaf"],
            displaced_leaf,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        _verify_displaced_live_leaf(entry)

    if not entry["remove"]:
        _link_no_replace(parent_fd, entry["stage_leaf"], entry["leaf"])

    # Record the pathname mutation before cleanup or durability calls. Recovery
    # also inspects inode identity, covering a syscall wrapper that mutates and
    # then raises before Python can execute this assignment.
    entry["committed"] = True
    os.fsync(parent_fd)


def _unlink_private_leaf_resilient(parent_fd: int, leaf: str) -> None:
    """Treat an unlink-then-raise wrapper as success when the name is gone."""

    try:
        os.unlink(leaf, dir_fd=parent_fd)
    except BaseException:
        if _leaf_stat_no_follow(parent_fd, leaf) is not None:
            raise


def _claim_and_remove_expected_leaf(entry: dict, expected_identity) -> bool:
    """Atomically move a live name, validate the moved inode, then remove it."""

    parent_fd = entry["parent_fd"]
    claim_leaf = _transaction_leaf(entry["leaf"], "rollback-claim")
    entry["recovery_claim_leaf"] = claim_leaf
    try:
        os.rename(
            entry["leaf"],
            claim_leaf,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
    except BaseException:
        if _leaf_stat_no_follow(parent_fd, claim_leaf) is None:
            entry["recovery_claim_leaf"] = None
            raise

    claimed_stat = _leaf_stat_no_follow(parent_fd, claim_leaf)
    if claimed_stat is None:
        entry["recovery_claim_leaf"] = None
        return False
    if _stat_identity(claimed_stat) != expected_identity:
        try:
            _link_no_replace(parent_fd, claim_leaf, entry["leaf"])
        except BaseException:
            if not _leaf_matches_identity(
                parent_fd,
                entry["leaf"],
                _stat_identity(claimed_stat),
            ):
                entry["preserve_recovery_artifacts"] = True
                raise
        _unlink_private_leaf_resilient(parent_fd, claim_leaf)
        entry["recovery_claim_leaf"] = None
        raise OSError("live restore target changed during automatic recovery")

    _unlink_private_leaf_resilient(parent_fd, claim_leaf)
    entry["recovery_claim_leaf"] = None
    return True


def _restore_displaced_no_replace(entry: dict) -> bool:
    """Restore a displaced live inode without overwriting a concurrent entry."""

    displaced_leaf = entry.get("displaced_leaf")
    if displaced_leaf is None:
        return False
    displaced_stat = _leaf_stat_no_follow(entry["parent_fd"], displaced_leaf)
    if displaced_stat is None:
        return False
    displaced_identity = _stat_identity(displaced_stat)
    try:
        _link_no_replace(entry["parent_fd"], displaced_leaf, entry["leaf"])
    except BaseException:
        if not _leaf_matches_identity(
            entry["parent_fd"],
            entry["leaf"],
            displaced_identity,
        ):
            entry["preserve_recovery_artifacts"] = True
            raise
    _unlink_private_leaf_resilient(entry["parent_fd"], displaced_leaf)
    entry["displaced_leaf"] = None
    return True


def _rollback_staged_entry(entry: dict) -> None:
    parent_fd = entry["parent_fd"]
    live_stat = _leaf_stat_no_follow(parent_fd, entry["leaf"])
    displaced_present = (
        entry.get("displaced_leaf") is not None
        and _leaf_stat_no_follow(parent_fd, entry["displaced_leaf"]) is not None
    )

    if live_stat is not None and _stat_identity(live_stat) == entry.get(
        "stage_identity"
    ):
        if _sha256_leaf_no_follow(parent_fd, entry["leaf"]) != entry.get(
            "stage_hash"
        ):
            entry["preserve_recovery_artifacts"] = True
            raise OSError("partially restored target changed before recovery")
        _claim_and_remove_expected_leaf(entry, entry["stage_identity"])
        live_stat = None

    if displaced_present:
        if live_stat is not None:
            entry["preserve_recovery_artifacts"] = True
            raise OSError("concurrent live target prevents automatic recovery")
        _restore_displaced_no_replace(entry)
    elif entry["existed"]:
        # No displacement occurred when the original inode is still at the
        # pathname. Any content change belongs to the concurrent writer.
        if live_stat is not None:
            entry["committed"] = False
            return
        backup_leaf = entry.get("backup_leaf")
        if backup_leaf is None:
            raise OSError("original live target is unavailable for recovery")
        try:
            _link_no_replace(parent_fd, backup_leaf, entry["leaf"])
        except BaseException:
            entry["preserve_recovery_artifacts"] = True
            raise
    elif live_stat is not None:
        # A file appeared while an absent-target installation was attempted.
        # It is not our staged inode, so preserve it instead of overwriting it.
        entry["committed"] = False
        return

    os.fsync(parent_fd)
    entry["committed"] = False


def _cleanup_staged_entry(entry: dict) -> None:
    parent_fd = entry.get("parent_fd")
    if parent_fd is None:
        return
    cleanup_keys = ["stage_leaf"]
    if not entry.get("preserve_recovery_artifacts"):
        cleanup_keys.extend(
            ("backup_leaf", "displaced_leaf", "recovery_claim_leaf")
        )
    for key in cleanup_keys:
        leaf = entry.get(key)
        if leaf is not None:
            try:
                os.unlink(leaf, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            except OSError:
                pass
            entry[key] = None
    try:
        os.fsync(parent_fd)
    except OSError:
        pass
    os.close(parent_fd)
    entry["parent_fd"] = None
    for directory in reversed(entry.get("created_dirs", [])):
        try:
            os.rmdir(directory)
        except OSError:
            pass
    entry["created_dirs"] = []


class _SnapshotExistsError(OSError):
    """Raised when the atomic snapshot-slot creation finds an existing name."""


def _same_object(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _directory_entry_matches_fd(parent_fd: int, leaf: str, descriptor: int) -> bool:
    """Return whether one no-follow directory entry still names ``descriptor``."""

    try:
        entry_stat = os.stat(
            leaf,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        opened_stat = os.fstat(descriptor)
    except OSError:
        return False
    return stat.S_ISDIR(entry_stat.st_mode) and _same_object(entry_stat, opened_stat)


def _open_snapshot_creation(store: str, snapshot_id: str) -> dict:
    """Atomically create and anchor a new store/slot/files hierarchy."""

    destination = snapshot_path(store, snapshot_id)
    store_root = os.path.dirname(destination)
    view = {
        "destination": destination,
        "store_parent_fd": None,
        "store_fd": None,
        "slot_fd": None,
        "files_fd": None,
        "store_leaf": None,
        "slot_leaf": snapshot_id,
        "store_created": False,
        "slot_created": False,
    }
    try:
        store_parent_fd, store_leaf = _open_parent_directory_no_follow(
            store_root,
            create=True,
        )
        view["store_parent_fd"] = store_parent_fd
        view["store_leaf"] = store_leaf
        try:
            os.mkdir(store_leaf, mode=0o700, dir_fd=store_parent_fd)
        except FileExistsError:
            pass
        else:
            view["store_created"] = True

        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        store_fd = os.open(store_leaf, directory_flags, dir_fd=store_parent_fd)
        view["store_fd"] = store_fd
        if not _directory_entry_matches_fd(store_parent_fd, store_leaf, store_fd):
            raise OSError("snapshot store changed while it was opened")

        try:
            os.mkdir(snapshot_id, mode=0o700, dir_fd=store_fd)
        except FileExistsError as exc:
            raise _SnapshotExistsError("snapshot slot already exists") from exc
        view["slot_created"] = True
        slot_fd = os.open(snapshot_id, directory_flags, dir_fd=store_fd)
        view["slot_fd"] = slot_fd
        if not _directory_entry_matches_fd(store_fd, snapshot_id, slot_fd):
            raise OSError("snapshot slot changed while it was opened")

        os.mkdir("files", mode=0o700, dir_fd=slot_fd)
        files_fd = os.open("files", directory_flags, dir_fd=slot_fd)
        view["files_fd"] = files_fd
        if not _directory_entry_matches_fd(slot_fd, "files", files_fd):
            raise OSError("snapshot files directory changed while it was opened")
        return view
    except BaseException:
        _cleanup_snapshot_creation(view)
        raise


def _open_snapshot_target_parent(files_fd: int, relative_path: str):
    """Create a snapshot-relative parent chain beneath an anchored files dir."""

    components = _snapshot_components(relative_path)
    directory_fd = os.dup(files_fd)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        for component in components[:-1]:
            try:
                next_fd = os.open(
                    component,
                    directory_flags,
                    dir_fd=directory_fd,
                )
            except FileNotFoundError:
                os.mkdir(component, mode=0o700, dir_fd=directory_fd)
                next_fd = os.open(
                    component,
                    directory_flags,
                    dir_fd=directory_fd,
                )
            os.close(directory_fd)
            directory_fd = next_fd
        return directory_fd, components[-1]
    except BaseException:
        os.close(directory_fd)
        raise


def _snapshot_copy_source(
    files_fd: int,
    source: str,
    relative_path: str,
    *,
    trusted_root: str,
) -> tuple[str, int]:
    source_fd, source_stat = _open_regular_no_follow(
        source,
        trusted_root=trusted_root,
    )
    target_parent_fd = None
    try:
        target_parent_fd, leaf = _open_snapshot_target_parent(
            files_fd,
            relative_path,
        )
        return _copy_open_source_to_snapshot_at(
            source_fd,
            source_stat,
            target_parent_fd,
            leaf,
        )
    finally:
        if target_parent_fd is not None:
            os.close(target_parent_fd)
        os.close(source_fd)


def _write_snapshot_manifest(slot_fd: int, manifest: dict) -> None:
    manifest_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    manifest_flags |= getattr(os, "O_BINARY", 0)
    manifest_fd = os.open("manifest.json", manifest_flags, 0o600, dir_fd=slot_fd)
    try:
        with os.fdopen(manifest_fd, "w", encoding="utf-8", closefd=False) as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
            fh.flush()
        os.fsync(manifest_fd)
    finally:
        os.close(manifest_fd)


def _snapshot_creation_is_published(view: dict) -> bool:
    """Check every created handle is still reachable at its intended name."""

    if not _directory_entry_matches_fd(
        view["store_parent_fd"],
        view["store_leaf"],
        view["store_fd"],
    ):
        return False
    if not _directory_entry_matches_fd(
        view["store_fd"],
        view["slot_leaf"],
        view["slot_fd"],
    ):
        return False
    if not _directory_entry_matches_fd(view["slot_fd"], "files", view["files_fd"]):
        return False
    try:
        published_stat = os.stat(view["destination"], follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISDIR(published_stat.st_mode) and _same_object(
        published_stat,
        os.fstat(view["slot_fd"]),
    )


def _clear_directory_fd(directory_fd: int) -> None:
    """Best-effort recursive cleanup constrained to one anchored directory."""

    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    for name in os.listdir(directory_fd):
        try:
            entry_stat = os.stat(
                name,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(entry_stat.st_mode):
            try:
                child_fd = os.open(name, directory_flags, dir_fd=directory_fd)
            except OSError:
                continue
            try:
                _clear_directory_fd(child_fd)
                if _directory_entry_matches_fd(directory_fd, name, child_fd):
                    try:
                        os.rmdir(name, dir_fd=directory_fd)
                    except OSError:
                        pass
            finally:
                os.close(child_fd)
        else:
            try:
                os.unlink(name, dir_fd=directory_fd)
            except OSError:
                pass


def _close_snapshot_creation(view: dict) -> None:
    for key in ("files_fd", "slot_fd", "store_fd", "store_parent_fd"):
        descriptor = view.get(key)
        if descriptor is not None:
            os.close(descriptor)
            view[key] = None


def _cleanup_snapshot_creation(view: dict) -> None:
    """Remove only the exact newly-created objects still anchored by ``view``."""

    slot_fd = view.get("slot_fd")
    store_fd = view.get("store_fd")
    store_parent_fd = view.get("store_parent_fd")
    try:
        if slot_fd is not None and view.get("slot_created"):
            _clear_directory_fd(slot_fd)
            if store_fd is not None and _directory_entry_matches_fd(
                store_fd,
                view["slot_leaf"],
                slot_fd,
            ):
                try:
                    os.rmdir(view["slot_leaf"], dir_fd=store_fd)
                except OSError:
                    pass
        if (
            view.get("store_created")
            and store_fd is not None
            and store_parent_fd is not None
            and _directory_entry_matches_fd(
                store_parent_fd,
                view["store_leaf"],
                store_fd,
            )
        ):
            try:
                os.rmdir(view["store_leaf"], dir_fd=store_parent_fd)
            except OSError:
                pass
    finally:
        _close_snapshot_creation(view)


def git_state(repo: str) -> dict:
    def g(*args):
        try:
            p = subprocess.run(
                ["git", "-C", repo, *args], capture_output=True, check=False, timeout=30
            )
            return p.stdout.decode("utf-8", "replace").strip() if p.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    porcelain = g("status", "--porcelain") or ""
    return {
        "repo": repo,
        "head": g("rev-parse", "HEAD"),
        "branch": g("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty_file_count": len([x for x in porcelain.splitlines() if x.strip()]),
    }


def cmd_snapshot(args) -> int:
    snap_id = utc_stamp() if args.id is None else args.id
    try:
        dest = snapshot_path(args.store, snap_id)
    except ValueError:
        print("invalid snapshot id", file=sys.stderr)
        return 2

    if not _supports_no_follow_directory_fds():
        print(
            "secure atomic snapshot creation is unavailable on this platform",
            file=sys.stderr,
        )
        return 2

    try:
        creation = _open_snapshot_creation(args.store, snap_id)
    except _SnapshotExistsError:
        print(
            f"refusing to overwrite existing snapshot {snap_id!r} at {dest}",
            file=sys.stderr,
        )
        return 2
    except OSError:
        print("snapshot failed safely", file=sys.stderr)
        return 2

    state_file = getattr(args, "state_file", DEFAULT_STATE_FILE)

    manifest = {
        "schema": "config-snapshot/2",
        "id": snap_id,
        "created_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "config_root": args.root,
        "git": git_state(args.repo) if args.repo else None,
        "files": {},
        "absent_files": [],
    }

    copied = 0
    try:
        for abspath, rel in iter_files(args.root):
            digest, size = _snapshot_copy_source(
                creation["files_fd"],
                abspath,
                rel,
                trusted_root=args.root,
            )
            manifest["files"][rel] = {
                "sha256": digest,
                "size": size,
            }
            copied += 1

        if state_file:
            try:
                state_fd, state_stat = _open_regular_no_follow(
                    state_file,
                    trusted_root=os.path.dirname(state_file),
                )
            except FileNotFoundError:
                manifest["absent_files"].append(GLOBAL_APP_STATE_LOGICAL)
            else:
                target_parent_fd = None
                try:
                    target_parent_fd, target_leaf = _open_snapshot_target_parent(
                        creation["files_fd"],
                        GLOBAL_APP_STATE_LOGICAL,
                    )
                    digest, size = _copy_open_source_to_snapshot_at(
                        state_fd,
                        state_stat,
                        target_parent_fd,
                        target_leaf,
                    )
                finally:
                    if target_parent_fd is not None:
                        os.close(target_parent_fd)
                    os.close(state_fd)
                manifest["files"][GLOBAL_APP_STATE_LOGICAL] = {
                    "sha256": digest,
                    "size": size,
                }
                copied += 1
        else:
            manifest["absent_files"].append(GLOBAL_APP_STATE_LOGICAL)

        _write_snapshot_manifest(creation["slot_fd"], manifest)
        os.fsync(creation["files_fd"])
        os.fsync(creation["slot_fd"])
        os.fsync(creation["store_fd"])
        if creation["store_created"]:
            os.fsync(creation["store_parent_fd"])
        if not _snapshot_creation_is_published(creation):
            raise OSError("snapshot hierarchy changed before publication")
    except BaseException as exc:
        _cleanup_snapshot_creation(creation)
        if not isinstance(exc, (OSError, ValueError, TypeError)):
            raise
        print("snapshot failed safely", file=sys.stderr)
        return 2

    _close_snapshot_creation(creation)

    print(f"snapshot {snap_id}: {copied} file(s) -> {dest}")
    if manifest["git"]:
        print(
            f"  pinned to git {manifest['git'].get('head')} "
            f"({manifest['git'].get('branch')}), "
            f"{manifest['git'].get('dirty_file_count')} dirty file(s)"
        )
    return 0


def cmd_list(args) -> int:
    if not os.path.isdir(args.store):
        print("no snapshots yet")
        return 0
    rows = []
    for entry in sorted(os.listdir(args.store)):
        try:
            entry_path = snapshot_path(args.store, entry)
        except ValueError:
            continue
        mpath = os.path.join(entry_path, "manifest.json")
        if not os.path.isfile(mpath):
            continue
        try:
            with open(mpath, encoding="utf-8") as fh:
                m = json.load(fh)
        except (ValueError, OSError):
            continue
        rows.append(
            (entry, m.get("created_utc"), len(m.get("files", {})), (m.get("git") or {}).get("head"))
        )
    if not rows:
        print("no snapshots yet")
        return 0
    print(f"{'id':28s} {'created':22s} {'files':>6s}  git")
    for entry, created, nfiles, head in rows:
        print(f"{entry:28s} {str(created)[:22]:22s} {nfiles:6d}  {str(head)[:12]}")
    return 0


def _plan(args):
    """Compute (changed, missing_in_live, extra_in_live) vs a snapshot."""
    try:
        view = _open_snapshot_view(args.store, args.id)
    except OSError:
        return None
    try:
        manifest_hashes = {}
        manifest_absent = set()
        manifest_valid = False
        try:
            with os.fdopen(
                os.dup(view["manifest_fd"]),
                encoding="utf-8",
            ) as manifest_file:
                manifest = json.load(manifest_file)
            schema = manifest.get("schema")
            if schema not in {"config-snapshot/1", "config-snapshot/2"}:
                raise ValueError("unsupported snapshot manifest schema")
            manifest_files = manifest.get("files")
            if not isinstance(manifest_files, dict):
                raise TypeError("snapshot manifest files must be an object")
            if schema == "config-snapshot/2" and "absent_files" not in manifest:
                raise TypeError("current snapshot manifest must record absent files")
            absent_files = manifest.get("absent_files", [])
            if not isinstance(absent_files, list) or any(
                not isinstance(rel, str) or rel not in EXTERNAL_FILE_TARGETS
                for rel in absent_files
            ):
                raise TypeError(
                    "snapshot manifest absent_files must name external files"
                )
            if len(absent_files) != len(set(absent_files)):
                raise ValueError(
                    "snapshot manifest absent_files must not contain duplicates"
                )
            manifest_absent = set(absent_files)
            if manifest_absent & set(manifest_files):
                raise ValueError("snapshot cannot contain and omit the same file")
            if schema == "config-snapshot/2" and any(
                (rel in manifest_files) == (rel in manifest_absent)
                for rel in EXTERNAL_FILE_TARGETS
            ):
                raise ValueError(
                    "current snapshot must classify each external file exactly once"
                )
            for rel, metadata in manifest_files.items():
                _snapshot_components(rel)
                if not isinstance(metadata, dict):
                    raise TypeError("snapshot manifest file entries are invalid")
                digest = metadata.get("sha256")
                size = metadata.get("size")
                if (
                    not isinstance(digest, str)
                    or re.fullmatch(r"[0-9a-f]{64}", digest) is None
                    or not isinstance(size, int)
                    or isinstance(size, bool)
                    or size < 0
                ):
                    raise TypeError("snapshot manifest file metadata is invalid")
                manifest_hashes[rel] = digest
            manifest_valid = True
        except (OSError, ValueError, TypeError, AttributeError):
            pass

        try:
            snap_rel = set(_walk_snapshot_files(view["files_fd"]))
        except OSError:
            snap_rel = set()
            manifest_valid = False
        snapshot_hashes = {}
        if manifest_valid and set(manifest_hashes) != snap_rel:
            manifest_valid = False
        if manifest_valid:
            for rel in sorted(snap_rel):
                source_fd = None
                try:
                    source_fd, _ = _open_snapshot_file(view["files_fd"], rel)
                    digest = _sha256_open_file(source_fd)
                except OSError:
                    manifest_valid = False
                    break
                finally:
                    if source_fd is not None:
                        os.close(source_fd)
                snapshot_hashes[rel] = digest
                if digest != manifest_hashes[rel]:
                    manifest_valid = False
                    break
        state_file = getattr(args, "state_file", DEFAULT_STATE_FILE)
        live_files = {
            rel: abspath
            for abspath, rel in iter_snapshot_files(args.root, state_file)
        }
        live_rel = set(live_files)
        explicitly_absent = []
        for rel in sorted(manifest_absent):
            try:
                absent_target = restore_destination(args, rel)
            except ValueError:
                manifest_valid = False
                continue
            if os.path.lexists(absent_target):
                explicitly_absent.append(rel)

        changed, same = [], []
        for rel in sorted(snap_rel & live_rel):
            trusted_live_root = (
                os.path.dirname(state_file)
                if rel == GLOBAL_APP_STATE_LOGICAL
                else args.root
            )
            try:
                live_hash = _sha256_regular_no_follow(
                    live_files[rel],
                    trusted_root=trusted_live_root,
                )
            except OSError:
                live_hash = None
            if (
                snapshot_hashes.get(rel) is not None
                and live_hash == snapshot_hashes[rel]
            ):
                same.append(rel)
            else:
                changed.append(rel)
        return {
            "changed": changed,
            "same": same,
            "only_in_snapshot": sorted(snap_rel - live_rel),
            "only_in_live": sorted((live_rel - snap_rel) - manifest_absent),
            "explicitly_absent": explicitly_absent,
            "manifest_hashes": manifest_hashes,
            "manifest_valid": manifest_valid,
            "snapshot_view": view,
        }
    except BaseException:
        _close_snapshot_view(view)
        raise


def cmd_diff(args) -> int:
    try:
        plan = _plan(args)
    except ValueError:
        print("invalid snapshot id", file=sys.stderr)
        return 2
    if plan is None:
        print(f"snapshot {args.id!r} not found or empty", file=sys.stderr)
        return 2
    try:
        print(f"snapshot {args.id} vs live {args.root}")
        print(f"  identical          : {len(plan['same'])}")
        print(f"  differing          : {len(plan['changed'])}")
        for rel in plan["changed"]:
            print(f"      M {rel}")
        print(f"  only in snapshot   : {len(plan['only_in_snapshot'])}")
        for rel in plan["only_in_snapshot"]:
            print(f"      - {rel}  (restore would re-create)")
        print(f"  only in live       : {len(plan['only_in_live'])}")
        for rel in plan["only_in_live"]:
            print(f"      + {rel}  (restore LEAVES this in place)")
        print(f"  explicitly absent  : {len(plan['explicitly_absent'])}")
        for rel in plan["explicitly_absent"]:
            print(f"      D {rel}  (restore would remove)")
        return 0
    finally:
        _close_plan(plan)


def cmd_restore(args) -> int:
    try:
        plan = _plan(args)
    except ValueError:
        print("invalid snapshot id", file=sys.stderr)
        return 2
    if plan is None:
        print(f"snapshot {args.id!r} not found or empty", file=sys.stderr)
        return 2
    try:
        return _restore_plan(args, plan)
    finally:
        _close_plan(plan)


def _restore_plan(args, plan) -> int:
    if not plan["manifest_valid"]:
        print(f"snapshot {args.id!r} has no valid integrity manifest", file=sys.stderr)
        return 2

    to_write = plan["changed"] + plan["only_in_snapshot"]
    to_remove = plan["explicitly_absent"]
    if not to_write and not to_remove:
        print("live configuration already matches the snapshot; nothing to do")
        return 0

    destinations = {}
    for rel in to_write:
        expected_hash = plan["manifest_hashes"].get(rel)
        if not expected_hash:
            print(f"refusing snapshot source without a hash for {rel}", file=sys.stderr)
            return 2
        try:
            destination = restore_destination(args, rel)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if os.path.islink(destination):
            print(
                f"refusing to restore through symlink target for {rel}",
                file=sys.stderr,
            )
            return 2
        try:
            _validate_destination_ancestors(destination)
        except (OSError, ValueError):
            print(
                f"refusing unsafe restore destination parent for {rel}",
                file=sys.stderr,
            )
            return 2
        destinations[rel] = destination

    removals = {}
    for rel in to_remove:
        try:
            destination = restore_destination(args, rel)
            _validate_destination_ancestors(destination)
        except (OSError, ValueError):
            print(f"refusing unsafe deletion target for {rel}", file=sys.stderr)
            return 2
        if os.path.islink(destination) or not os.path.isfile(destination):
            print(f"refusing unsafe deletion target for {rel}", file=sys.stderr)
            return 2
        removals[rel] = destination

    print(f"restore {args.id} -> {args.root}")
    print(f"  will overwrite/create {len(to_write)} file(s):")
    for rel in to_write:
        print(f"      {rel}")
    print(f"  will remove {len(to_remove)} explicitly absent file(s):")
    for rel in to_remove:
        print(f"      {rel}")
    live_only_untouched = set(plan["only_in_live"]) - set(to_remove)
    print(f"  will LEAVE {len(live_only_untouched)} live-only file(s) untouched")

    if not args.confirm:
        print("\nrefusing to modify anything without --confirm (dry run)")
        return 1

    if not _supports_no_follow_directory_fds():
        print(
            "secure atomic restore is unavailable on this platform; no files changed",
            file=sys.stderr,
        )
        return 2

    # A rollback must itself be reversible.
    # The id is de-collided: two restores in the same second would otherwise
    # abort the second one (see unique_snapshot_id).
    pre_id = unique_snapshot_id(args.store, f"pre-restore-{utc_stamp()}")
    pre_args = argparse.Namespace(
        id=pre_id,
        store=args.store,
        root=args.root,
        state_file=getattr(args, "state_file", DEFAULT_STATE_FILE),
        repo=args.repo,
    )
    rc = cmd_snapshot(pre_args)
    if rc != 0:
        print("pre-restore snapshot failed; aborting restore", file=sys.stderr)
        return rc

    # Publish the recovery command before the first transaction step so it is
    # still present if the process or machine stops during the restore.
    _print_undo(args, pre_id)

    pre_plan = _plan(pre_args)
    if pre_plan is None:
        print("pre-restore snapshot could not be reopened safely", file=sys.stderr)
        return 2
    try:
        if not pre_plan["manifest_valid"]:
            print("pre-restore snapshot failed integrity validation", file=sys.stderr)
            return 2
        baseline_hashes = dict(pre_plan["manifest_hashes"])
    finally:
        _close_plan(pre_plan)

    entries = []
    try:
        for rel in to_write:
            source_fd = None
            try:
                source_fd, source_stat = _open_snapshot_file(
                    plan["snapshot_view"]["files_fd"],
                    rel,
                )
                entries.append(
                    _prepare_write_entry(
                        source_fd,
                        source_stat,
                        plan["manifest_hashes"][rel],
                        destinations[rel],
                        baseline_hashes.get(rel),
                    )
                )
            finally:
                if source_fd is not None:
                    os.close(source_fd)
        for rel in to_remove:
            entries.append(
                _prepare_remove_entry(
                    removals[rel],
                    baseline_hashes.get(rel),
                )
            )
    except BaseException as exc:
        for entry in reversed(entries):
            _cleanup_staged_entry(entry)
        if not isinstance(exc, OSError):
            raise
        print(
            "restore staging failed; live configuration unchanged",
            file=sys.stderr,
        )
        return 2

    try:
        for entry in entries:
            _commit_staged_entry(entry)
        for entry in entries:
            _verify_committed_entry(entry)
    except BaseException as exc:
        recovered = True
        for entry in reversed(entries):
            try:
                _rollback_staged_entry(entry)
            except BaseException:  # noqa: BLE001 - recover every touched entry
                recovered = False
        for entry in reversed(entries):
            try:
                _cleanup_staged_entry(entry)
            except BaseException:  # noqa: BLE001 - finish cleanup before re-raise
                recovered = False
        if not isinstance(exc, OSError):
            raise
        if recovered:
            print(
                "restore commit failed; original live configuration recovered",
                file=sys.stderr,
            )
        else:
            print(
                "restore commit failed and automatic recovery was incomplete; use the printed Undo command",
                file=sys.stderr,
            )
        return 2

    for entry in reversed(entries):
        _cleanup_staged_entry(entry)

    restored_count = len(to_write) + len(to_remove)
    print(f"\nrestored {restored_count} file state(s).")
    _print_undo(args, pre_id)
    return 0


def _add_common(parser, *, suppress_defaults: bool = False) -> None:
    """Attach the global options to a subparser too.

    argparse only accepts parent-level options BEFORE the subcommand, which makes
    `snapshot --repo .` a confusing usage error. Declaring them on both levels lets
    either ordering work.
    """
    default = argparse.SUPPRESS if suppress_defaults else DEFAULT_STORE
    parser.add_argument("--store", default=default, help="snapshot store directory")
    parser.add_argument(
        "--root",
        default=(
            argparse.SUPPRESS
            if suppress_defaults
            else os.path.join(HOME, ".claude")
        ),
        help="configuration root to snapshot/restore (default: ~/.claude)",
    )
    parser.add_argument(
        "--repo",
        default=argparse.SUPPRESS if suppress_defaults else os.getcwd(),
        help="git repo to pin the snapshot to",
    )
    parser.add_argument(
        "--state-file",
        default=argparse.SUPPRESS if suppress_defaults else DEFAULT_STATE_FILE,
        help="global Claude app/MCP state file (default: ~/.claude.json)",
    )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    _add_common(ap)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("snapshot", help="capture a known-good configuration")
    p.add_argument("--id", help="snapshot id (default: UTC timestamp)")
    _add_common(p, suppress_defaults=True)
    p.set_defaults(func=cmd_snapshot)

    p = sub.add_parser("list", help="list snapshots")
    _add_common(p, suppress_defaults=True)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("diff", help="show what a restore would change")
    p.add_argument("--id", required=True)
    _add_common(p, suppress_defaults=True)
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("restore", help="roll back to a snapshot")
    p.add_argument("--id", required=True)
    p.add_argument("--confirm", action="store_true", help="actually write files")
    _add_common(p, suppress_defaults=True)
    p.set_defaults(func=cmd_restore)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
