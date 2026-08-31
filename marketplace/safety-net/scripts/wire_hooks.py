#!/usr/bin/env python3
"""Merge installer-selected hooks into settings.json using portable exec form."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

from hook_exec_form import (
    configured_hook_invocation,
    configured_hook_script,
    hook_exec_argv,
    normalize_exec_path,
    resolve_git_bash,
)

MINIMUM_VERSION = "2.1.223"
_LOCAL_LOCKS: dict[str, threading.Lock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()
_UNSUPPORTED_XATTR_ERRNOS = {
    value
    for value in (
        getattr(errno, "ENOTSUP", None),
        getattr(errno, "EOPNOTSUPP", None),
    )
    if value is not None
}


def _version(value: str) -> tuple[int, int, int]:
    parts = value.split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"invalid minimumVersion: {value!r}")
    return tuple(int(part) for part in parts)


def _raise_minimum_version(settings: dict) -> bool:
    current = settings.get("minimumVersion")
    if current is None:
        settings["minimumVersion"] = MINIMUM_VERSION
        return True
    if not isinstance(current, str):
        raise TypeError("settings minimumVersion must be a semantic-version string")
    if _version(current) < _version(MINIMUM_VERSION):
        settings["minimumVersion"] = MINIMUM_VERSION
        return True
    return False


@contextmanager
def _settings_update_lock(settings_path: Path):
    """Serialize installer writers in-process and across processes."""

    key = str(settings_path)
    with _LOCAL_LOCKS_GUARD:
        local_lock = _LOCAL_LOCKS.setdefault(key, threading.Lock())
    with local_lock:
        lock_name = hashlib.sha256(key.encode("utf-8")).hexdigest()
        lock_path = Path(tempfile.gettempdir()) / f"claude-wire-hooks-{lock_name}.lock"
        with lock_path.open("a+b") as handle:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_xattrs(path: Path) -> dict[str, bytes]:
    """Read metadata that an atomic replacement would otherwise discard."""

    if not hasattr(os, "listxattr"):
        return {}
    try:
        names = os.listxattr(path, follow_symlinks=False)
    except OSError as exc:
        if exc.errno in _UNSUPPORTED_XATTR_ERRNOS:
            return {}
        raise
    return {
        name: os.getxattr(path, name, follow_symlinks=False)
        for name in names
    }


def _apply_xattrs(path: Path, attributes: dict[str, bytes]) -> None:
    if not attributes:
        return
    if not hasattr(os, "setxattr"):
        raise RuntimeError("cannot preserve settings extended attributes on this host")
    for name, value in attributes.items():
        os.setxattr(path, name, value, follow_symlinks=False)


def _metadata_signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_gid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _macos_acl_signature(path: Path) -> bytes:
    """Return only macOS extended ACL entries, or an empty portable marker."""

    if sys.platform != "darwin":
        return b""
    result = subprocess.run(
        ["/bin/ls", "-lde", str(path)],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "cannot inspect macOS settings ACL: "
            + result.stderr.decode("utf-8", errors="replace").strip()
        )
    return b"\n".join(result.stdout.splitlines()[1:])


def _atomic_publish(settings_path: Path, original: bytes, settings: dict) -> None:
    payload = (json.dumps(settings, indent=2) + "\n").encode("utf-8")
    source_stat = settings_path.stat()
    mode = stat.S_IMODE(source_stat.st_mode)
    xattrs = _read_xattrs(settings_path)
    acl = _macos_acl_signature(settings_path)
    descriptor, temporary = tempfile.mkstemp(
        dir=settings_path.parent,
        prefix=".settings.",
        suffix=".tmp",
    )
    try:
        temporary_path = Path(temporary)
        if sys.platform == "darwin":
            # CPython builds on macOS do not consistently expose the xattr
            # APIs, and chmod/chown alone cannot reproduce an extended ACL.
            # ``cp -p`` seeds the already-created sibling with the source's
            # ownership, mode, flags, xattrs, and ACL before its bytes change.
            copied = subprocess.run(
                ["/bin/cp", "-p", str(settings_path), str(temporary_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            if copied.returncode != 0:
                raise RuntimeError(
                    "cannot preserve macOS settings metadata: "
                    + (copied.stderr.strip() or "cp -p failed")
                )
        with os.fdopen(descriptor, "wb") as handle:
            os.ftruncate(handle.fileno(), 0)
            os.lseek(handle.fileno(), 0, os.SEEK_SET)
            temporary_stat = os.fstat(handle.fileno())
            if (
                hasattr(os, "fchown")
                and (temporary_stat.st_uid, temporary_stat.st_gid)
                != (source_stat.st_uid, source_stat.st_gid)
            ):
                os.fchown(handle.fileno(), source_stat.st_uid, source_stat.st_gid)
            os.fchmod(handle.fileno(), mode)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _apply_xattrs(temporary_path, xattrs)
        if _macos_acl_signature(temporary_path) != acl:
            raise RuntimeError("cannot preserve macOS settings ACL")
        with temporary_path.open("rb") as handle:
            os.fsync(handle.fileno())
        # A non-cooperating editor does not honor our lock. Refuse to replace
        # bytes that changed while the merged candidate was being prepared.
        if (
            settings_path.read_bytes() != original
            or _metadata_signature(settings_path.stat())
            != _metadata_signature(source_stat)
            or _read_xattrs(settings_path) != xattrs
            or _macos_acl_signature(settings_path) != acl
        ):
            raise RuntimeError("settings changed concurrently; rerun hook wiring")
        os.replace(temporary_path, settings_path)
        if hasattr(os, "O_DIRECTORY"):
            directory = os.open(settings_path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _reconcile_existing_hooks(
    settings: dict,
    config_dir: Path,
    *,
    native_windows: bool,
    platform_name: str,
    bash_executable: str | None,
) -> int:
    """Materialize every registered local hook for this host."""

    resolved_bash = bash_executable if native_windows else None
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        raise TypeError("settings hooks must be an object")
    changed = 0
    missing = []
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            raise TypeError(f"settings hooks.{event} must be a list")
        kept_groups = []
        for group in groups:
            if not isinstance(group, dict):
                kept_groups.append(group)
                continue
            handlers = group.get("hooks", [])
            if not isinstance(handlers, list):
                raise TypeError(f"settings hooks.{event} group hooks must be a list")
            kept_handlers = []
            for handler in handlers:
                if not isinstance(handler, dict) or handler.get("type", "command") != "command":
                    kept_handlers.append(handler)
                    continue
                command = handler.get("command", "")
                if not isinstance(command, str):
                    raise TypeError(f"settings hooks.{event} command must be a string")
                script, trailing_args = configured_hook_invocation(handler)
                if script:
                    target = config_dir / "hooks" / script
                    if not target.is_file():
                        missing.append(str(target))
                        kept_handlers.append(handler)
                        continue
                    if script.endswith(".py"):
                        new_command, new_args = hook_exec_argv(
                            config_dir,
                            script,
                            native_windows=native_windows,
                            bash_executable=resolved_bash,
                            bash_is_validated=native_windows,
                        )
                        new_args.extend(trailing_args)
                    elif native_windows:
                        new_command = resolved_bash
                        new_args = [normalize_exec_path(target), *trailing_args]
                    else:
                        new_command = normalize_exec_path(target)
                        new_args = trailing_args
                    if handler.get("command") != new_command or handler.get("args") != new_args:
                        handler["command"] = new_command
                        handler["args"] = new_args
                        changed += 1
                    kept_handlers.append(handler)
                    continue
                if Path(command).name == "afplay" and platform_name != "darwin":
                    changed += 1
                    continue
                kept_handlers.append(handler)
            if kept_handlers:
                group["hooks"] = kept_handlers
                kept_groups.append(group)
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]

    status_line = settings.get("statusLine")
    if isinstance(status_line, dict) and status_line.get("type") == "command":
        if native_windows:
            del settings["statusLine"]
            changed += 1
        else:
            launcher = config_dir / "bin" / "statusline-launcher"
            if launcher.is_file():
                materialized = normalize_exec_path(launcher)
                if status_line.get("command") != materialized:
                    status_line["command"] = materialized
                    changed += 1
    if missing:
        raise RuntimeError(
            "cannot materialize settings; registered hook files are missing: "
            + ", ".join(sorted(set(missing)))
        )
    return changed


def wire_hooks(
    settings_path: Path,
    configs: list[str],
    *,
    reconcile_existing: bool = False,
    native_windows: bool | None = None,
    platform_name: str | None = None,
    bash_executable: str | None = None,
) -> int:
    # Preserve the caller-visible configuration directory for hook argv. The
    # settings file itself may be a dotfiles symlink whose physical target has
    # no sibling hooks directory. Lock and publish the resolved target so all
    # aliases serialize without replacing the symlink.
    logical_settings_path = Path(
        os.path.abspath(os.fspath(settings_path.expanduser()))
    )
    logical_config_dir = logical_settings_path.parent
    settings_path = logical_settings_path.resolve()
    if native_windows is None:
        native_windows = os.name == "nt"
    if platform_name is None:
        platform_name = sys.platform
    resolved_bash = resolve_git_bash(bash_executable) if native_windows else None
    with _settings_update_lock(settings_path):
        original = settings_path.read_bytes()
        settings = json.loads(original)
        if not isinstance(settings, dict):
            raise TypeError("settings root must be an object")
        floor_changed = _raise_minimum_version(settings)
        hooks = settings.get("hooks", {})
        if configs or reconcile_existing:
            if "hooks" not in settings:
                settings["hooks"] = hooks
            if not isinstance(hooks, dict):
                raise TypeError("settings hooks must be an object")

        if reconcile_existing:
            _reconcile_existing_hooks(
                settings,
                logical_config_dir,
                native_windows=native_windows,
                platform_name=platform_name,
                bash_executable=resolved_bash,
            )

        added = 0
        for config in configs:
            parts = config.split("|")
            if len(parts) < 3:
                raise ValueError(f"invalid hook configuration: {config!r}")
            event = parts[0]
            timeout = int(parts[-1])
            hook_file = parts[-2]
            matcher = "|".join(parts[1:-2])
            if not event or Path(hook_file).name != hook_file or not hook_file.endswith(".py"):
                raise ValueError(f"invalid hook configuration: {config!r}")
            if timeout <= 0:
                raise ValueError(f"invalid hook timeout: {timeout}")
            command, args = hook_exec_argv(
                logical_config_dir,
                hook_file,
                native_windows=native_windows,
                bash_executable=resolved_bash,
                bash_is_validated=native_windows,
            )

            event_hooks = hooks.setdefault(event, [])
            if not isinstance(event_hooks, list):
                raise TypeError(f"settings hooks.{event} must be a list")

            matcher_group = next(
                (
                    group
                    for group in event_hooks
                    if isinstance(group, dict)
                    and (group.get("matcher") or "") == matcher
                    and isinstance(group.get("hooks", []), list)
                ),
                None,
            )
            existing = None
            if matcher_group is not None:
                existing = next(
                    (
                        handler
                        for handler in matcher_group["hooks"]
                        if isinstance(handler, dict)
                        and not handler.get("if")
                        and configured_hook_script(handler) == hook_file
                    ),
                    None,
                )
            if existing is not None:
                _existing_script, existing_trailing_args = configured_hook_invocation(existing)
                existing.update(
                    {
                        "type": "command",
                        "command": command,
                        "args": [*args, *existing_trailing_args],
                        "timeout": timeout,
                    }
                )
                continue

            entry = {
                "hooks": [{
                    "type": "command",
                    "command": command,
                    "args": args,
                    "timeout": timeout,
                }],
            }
            if matcher:
                entry["matcher"] = matcher
            event_hooks.append(entry)
            added += 1

        if floor_changed or configs or reconcile_existing:
            _atomic_publish(settings_path, original, settings)
        return added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reconcile-existing",
        action="store_true",
        help="rewrite every local hook registration for the current host",
    )
    parser.add_argument(
        "--ensure-minimum-version",
        action="store_true",
        help="raise minimumVersion without requiring a hook registration",
    )
    parser.add_argument("settings", type=Path)
    parser.add_argument("configs", nargs="*")
    args = parser.parse_args(argv)
    if not args.configs and not (args.reconcile_existing or args.ensure_minimum_version):
        parser.error(
            "at least one config, --reconcile-existing, or "
            "--ensure-minimum-version is required"
        )
    added = wire_hooks(
        args.settings,
        args.configs,
        reconcile_existing=args.reconcile_existing,
    )
    print(f"Wired {added} new hooks into {args.settings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
