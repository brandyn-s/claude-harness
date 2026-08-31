#!/usr/bin/env python3
"""Run non-billable release qualification for the local Claude Code architecture.

The qualification intentionally never sends a prompt or contacts Anthropic. It checks
the installed CLI version, the settings and hook execution contracts, and two
local lifecycle hooks against disposable files. Candidate checkouts can be
tested before deployment with ``--config-root`` even when settings point at the
live ``~/.claude`` launcher.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import NamedTuple

sys.dont_write_bytecode = True

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from hook_exec_form import (
    configured_hook_embeds_dispatcher,
    configured_hook_is_malformed,
    configured_hook_script,
    configured_hook_uses_dispatcher,
    is_bash_launcher,
)

VERSION_RE = re.compile(r"(?<!\d)(\d+)\.(\d+)\.(\d+)(?!\d)")
SHELL_TOKENS = (
    "$", "~", "%USERPROFILE%", "%HOME%", "`", "\n", "\r",
    "&&", "||", ";", "|", ">", "<",
)
ARG_CONTROL_TOKENS = ("\x00", "\n", "\r")


class QualificationResult(NamedTuple):
    name: str
    ok: bool
    detail: str


def parse_version(value: str) -> tuple[int, int, int]:
    """Extract a semantic three-part version from Claude's CLI output."""

    match = VERSION_RE.search(value or "")
    if not match:
        raise ValueError("no three-part version found")
    return tuple(int(part) for part in match.groups())


def version_at_least(actual: str, required: str) -> bool:
    try:
        return parse_version(actual) >= parse_version(required)
    except (TypeError, ValueError):
        return False


def iter_command_hooks(settings: dict) -> Iterable[tuple[str, dict]]:
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        return
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            inner = group.get("hooks", [])
            if not isinstance(inner, list):
                continue
            for hook in inner:
                if isinstance(hook, dict) and hook.get("type", "command") == "command":
                    yield str(event), hook


def find_registered_hook(
    settings: dict,
    event: str,
    script: str,
    *,
    required_matcher: str | None = None,
    required_matchers: frozenset[str] | None = None,
    required_timeout: int | None = None,
) -> dict:
    groups = settings.get("hooks", {}).get(event, [])
    if not isinstance(groups, list):
        groups = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        matcher = group.get("matcher", "")
        if required_matcher is not None and matcher != required_matcher:
            continue
        matchers = frozenset(part.strip() for part in matcher.split("|") if part.strip()) if isinstance(matcher, str) else frozenset()
        inner = group.get("hooks", [])
        if not isinstance(inner, list):
            continue
        for hook in inner:
            if not isinstance(hook, dict) or hook.get("type", "command") != "command":
                continue
            if configured_hook_script(hook) != script:
                continue
            if required_matchers is not None and matchers != required_matchers:
                continue
            if required_timeout is not None and hook.get("timeout") != required_timeout:
                continue
            return hook
    raise LookupError(f"{event} does not register {script}")


def _dispatcher_target_token(hook: dict) -> str | None:
    """Return the raw script token from a supported structured dispatcher."""

    command = hook.get("command", "")
    args = hook.get("args", [])
    if not isinstance(command, str) or not isinstance(args, list):
        return None
    command_name = Path(command.replace("\\", "/")).name
    if command_name == "run-hook":
        return args[0] if args and isinstance(args[0], str) else None
    if (
        is_bash_launcher(command)
        and args
        and isinstance(args[0], str)
        and Path(args[0].replace("\\", "/")).name == "run-hook"
    ):
        return args[1] if len(args) > 1 and isinstance(args[1], str) else None
    return None


def validate_hook_exec_contract(
    settings: dict,
    *,
    config_root: Path | None = None,
) -> list[str]:
    """Require direct executable paths and structured arguments for hooks."""

    problems: list[str] = []
    for event, hook in iter_command_hooks(settings):
        command = hook.get("command")
        args = hook.get("args")
        label = f"{event} command"
        if not isinstance(command, str) or not command:
            problems.append(f"{label} is missing")
            continue
        if not (
            PurePosixPath(command).is_absolute()
            or PureWindowsPath(command).is_absolute()
        ) or any(token in command for token in SHELL_TOKENS):
            problems.append(f"{label} must be one absolute executable without shell expansion")
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            problems.append(f"{label} args must be a list of strings")
            continue
        if any(any(token in arg for token in ARG_CONTROL_TOKENS) for arg in args):
            problems.append(f"{label} args must not contain NUL or line breaks")
        if configured_hook_is_malformed(hook):
            if configured_hook_embeds_dispatcher(hook):
                problems.append(
                    f"{label} embeds dispatcher argv in command; use one executable "
                    "and put run-hook arguments in args"
                )
            else:
                problems.append(
                    f"{label} must use structured exec form with one absolute "
                    "executable and string args"
                )
        if configured_hook_uses_dispatcher(hook):
            script = configured_hook_script(hook)
            target_token = _dispatcher_target_token(hook)
            target_basename = (
                Path(target_token.strip("\"'").replace("\\", "/")).name
                if target_token is not None
                else None
            )
            if target_token is not None and (
                target_token != target_basename
                or not target_token.endswith(".py")
            ):
                problems.append(
                    f"{label} run-hook must name a hook script as an unquoted "
                    "basename; Python hook (.py) required"
                )
            elif not args or script is None:
                problems.append(f"{label} run-hook args must name a hook script")
        if config_root is None:
            continue

        command_path = Path(command)
        dispatcher_in_args = (
            args[0]
            if is_bash_launcher(command)
            and args
            and Path(args[0].replace("\\", "/")).name == "run-hook"
            else None
        )
        if command_path.name == "run-hook" or command_path.parent.name == "hooks":
            executable = config_root / "hooks" / command_path.name
        else:
            executable = command_path
        if not executable.is_file():
            problems.append(f"{label} executable does not exist: {executable}")
        elif not os.access(executable, os.X_OK):
            problems.append(f"{label} executable is not runnable: {executable}")
        if dispatcher_in_args is not None:
            dispatcher = config_root / "hooks" / "run-hook"
            if not dispatcher.is_file() or not os.access(dispatcher, os.X_OK):
                problems.append(f"{label} dispatcher does not exist or is not runnable: {dispatcher}")
        script = configured_hook_script(hook)
        if script is not None:
            script_path = config_root / "hooks" / script
            if not script_path.is_file():
                problems.append(f"{label} hook script does not exist: {script_path}")
    return problems


def validate_static_contracts(
    settings: dict,
    environment: Mapping[str, str],
    *,
    config_root: Path | None = None,
) -> list[str]:
    problems = validate_hook_exec_contract(settings, config_root=config_root)
    worktree = settings.get("worktree")
    if not isinstance(worktree, dict) or worktree.get("baseRef") != "fresh":
        problems.append("worktree.baseRef must be fresh")
    configured_env = settings.get("env", {})
    configured_child = configured_env.get("CLAUDE_CODE_CHILD_SESSION") if isinstance(configured_env, dict) else None
    if environment.get("CLAUDE_CODE_CHILD_SESSION") or configured_child:
        problems.append("top-level environment unexpectedly sets CLAUDE_CODE_CHILD_SESSION")
    return problems


def runtime_hook_command(hook: dict, config_root: Path) -> list[str]:
    """Resolve a configured hook to the equivalent candidate-checkout command."""

    command = hook.get("command", "")
    args = hook.get("args", [])
    if not isinstance(command, str) or not isinstance(args, list):
        raise TypeError("invalid command hook")
    if configured_hook_is_malformed(hook):
        raise ValueError("malformed structured hook command must not be remapped")
    if Path(command).name == "run-hook":
        executable = str(config_root / "hooks" / "run-hook").replace("\\", "/")
        return [executable, *args]
    if (
        is_bash_launcher(command)
        and args
        and isinstance(args[0], str)
        and Path(args[0].replace("\\", "/")).name == "run-hook"
    ):
        candidate = str(config_root / "hooks" / "run-hook").replace("\\", "/")
        return [command, candidate, *args[1:]]
    return [command, *args]


def _run_hook(command: list[str], payload: dict, env: dict, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
        env=env,
        cwd=str(cwd),
    )


def qualify_session_end(settings: dict, config_root: Path, receipt_dir: Path) -> QualificationResult:
    try:
        hook = find_registered_hook(settings, "SessionEnd", "session-end.py")
        isolated_root = receipt_dir / ".claude-release-qualification"
        isolated_hooks = isolated_root / "hooks"
        isolated_hooks.mkdir(parents=True)
        for filename in (
            "run-hook",
            "session-end.py",
            "session_runtime.py",
            "atomic_write.py",
        ):
            shutil.copy2(config_root / "hooks" / filename, isolated_hooks / filename)
        (isolated_hooks / "run-hook").chmod(0o755)
        command = runtime_hook_command(hook, isolated_root)
        env = dict(os.environ)
        for key in ("HOME", "USERPROFILE", "CLAUDE_CONFIG_DIR"):
            env.pop(key, None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["CLAUDE_SESSION_END_RECEIPT_DIR"] = str(receipt_dir)
        proc = _run_hook(
            command,
            {
                "hook_event_name": "SessionEnd",
                "session_id": "release-qualification",
                "transcript_path": "",
                "cwd": str(config_root),
                "reason": "release_qualification",
            },
            env,
            isolated_root,
        )
        receipt = receipt_dir / "release-qualification.json"
        data = json.loads(receipt.read_text(encoding="utf-8"))
        telemetry = list((isolated_root / "audit").glob("hook-fires-*.jsonl"))
        if (
            proc.returncode != 0
            or proc.stdout
            or proc.stderr
            or data.get("session_id") != "release-qualification"
            or len(telemetry) != 1
        ):
            return QualificationResult("session_end_homeless", False, "hook did not produce a clean bounded receipt")
        return QualificationResult(
            "session_end_homeless",
            True,
            "HOME-less SessionEnd wrote a disposable receipt and isolated telemetry",
        )
    except (OSError, ValueError, LookupError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return QualificationResult("session_end_homeless", False, f"{type(exc).__name__}: {exc}")


def qualify_config_change(settings: dict, config_root: Path, temp_dir: Path) -> QualificationResult:
    try:
        hook = find_registered_hook(
            settings,
            "ConfigChange",
            "config-change-validate.py",
            required_matcher="user_settings|project_settings|local_settings",
            required_timeout=30,
        )
        command = runtime_hook_command(hook, config_root)
        invalid = temp_dir / "invalid-settings.json"
        invalid.write_text('{"hooks":', encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["CLAUDE_CONFIG_DIR"] = str(temp_dir / "config")
        for source in ("user_settings", "project_settings", "local_settings"):
            blocked = _run_hook(
                command,
                {
                    "hook_event_name": "ConfigChange",
                    "source": source,
                    "file_path": str(invalid),
                },
                env,
                config_root,
            )
            decision = json.loads(blocked.stdout)
            if blocked.returncode != 0 or decision.get("decision") != "block":
                return QualificationResult(
                    "config_change_guard",
                    False,
                    f"malformed {source} were not blocked",
                )

        policy = _run_hook(
            command,
            {
                "hook_event_name": "ConfigChange",
                "source": "policy_settings",
                "file_path": str(temp_dir / "missing-policy.json"),
            },
            env,
            config_root,
        )
        if policy.returncode != 0 or policy.stdout or policy.stderr:
            return QualificationResult("config_change_guard", False, "policy settings were incorrectly blocked")
        return QualificationResult(
            "config_change_guard",
            True,
            "malformed user/project/local settings block; policy source remains advisory",
        )
    except (OSError, ValueError, LookupError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return QualificationResult("config_change_guard", False, f"{type(exc).__name__}: {exc}")


def _xattrs(path: Path) -> list[tuple[str, bytes]]:
    if not hasattr(os, "listxattr") or not hasattr(os, "getxattr"):
        if sys.platform == "darwin" and Path("/usr/bin/xattr").is_file():
            try:
                listed = subprocess.run(
                    ["/usr/bin/xattr", "-s", str(path)],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise OSError(errno.EIO, f"cannot inspect xattrs for {path}: {exc}") from exc
            if listed.returncode != 0:
                raise OSError(
                    errno.EIO,
                    f"cannot inspect xattrs for {path}: "
                    + listed.stderr.decode("utf-8", errors="replace").strip(),
                )
            values = []
            for raw_name in listed.stdout.splitlines():
                name = raw_name.decode("utf-8", errors="surrogateescape")
                try:
                    read = subprocess.run(
                        ["/usr/bin/xattr", "-p", "-s", "-x", name, str(path)],
                        capture_output=True,
                        timeout=5,
                        check=False,
                    )
                except (OSError, subprocess.SubprocessError) as exc:
                    raise OSError(
                        errno.EIO,
                        f"cannot read xattr {name!r} for {path}: {exc}",
                    ) from exc
                if read.returncode != 0:
                    raise OSError(
                        errno.EIO,
                        f"cannot read xattr {name!r} for {path}: "
                        + read.stderr.decode("utf-8", errors="replace").strip(),
                    )
                try:
                    value = bytes.fromhex(read.stdout.decode("ascii"))
                except (UnicodeDecodeError, ValueError) as exc:
                    raise OSError(
                        errno.EIO,
                        f"invalid xattr encoding for {name!r} on {path}",
                    ) from exc
                values.append((name, value))
            return values
        return []
    try:
        names = os.listxattr(path, follow_symlinks=False)
    except TypeError:
        names = os.listxattr(path)
    except OSError as exc:
        if exc.errno in {errno.ENODATA, errno.ENOTSUP, errno.EOPNOTSUPP}:
            return []
        raise
    values = []
    for name in sorted(names):
        try:
            value = os.getxattr(path, name, follow_symlinks=False)
        except TypeError:
            value = os.getxattr(path, name)
        except OSError as exc:
            if exc.errno in {errno.ENODATA, errno.ENOTSUP, errno.EOPNOTSUPP}:
                continue
            raise
        values.append((name, value))
    return values


def _macos_xattr_snapshot(paths: list[Path]) -> bytes | None:
    """Read all selected macOS xattrs in bounded native-command batches."""

    if hasattr(os, "listxattr") and hasattr(os, "getxattr"):
        return None
    if sys.platform != "darwin" or not Path("/usr/bin/xattr").is_file():
        raise OSError(errno.ENOTSUP, "complete xattr evidence is unavailable")

    outputs = []
    batch: list[str] = []
    batch_bytes = 0
    for path in paths:
        value = str(path)
        encoded_size = len(os.fsencode(value)) + 1
        if batch and batch_bytes + encoded_size > 32 * 1024:
            outputs.append(_run_macos_xattr_batch(batch))
            batch = []
            batch_bytes = 0
        batch.append(value)
        batch_bytes += encoded_size
    if batch:
        outputs.append(_run_macos_xattr_batch(batch))
    return b"\0--XATTR-BATCH--\0".join(outputs)


def _run_macos_xattr_batch(paths: list[str]) -> bytes:
    try:
        result = subprocess.run(
            ["/usr/bin/xattr", "-l", "-s", "-x", *paths],
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OSError(errno.EIO, f"cannot inspect macOS xattrs: {exc}") from exc
    if result.returncode != 0:
        raise OSError(
            errno.EIO,
            "cannot inspect macOS xattrs: "
            + result.stderr.decode("utf-8", errors="replace").strip(),
        )
    return result.stdout


def _macos_acl_snapshot(paths: list[Path]) -> bytes | None:
    """Read ACL evidence for every selected macOS path in bounded batches."""

    if sys.platform != "darwin":
        return None
    if not Path("/bin/ls").is_file():
        raise OSError(errno.ENOTSUP, "complete macOS ACL evidence is unavailable")

    outputs = []
    batch: list[str] = []
    batch_bytes = 0
    for path in paths:
        value = str(path)
        encoded_size = len(os.fsencode(value)) + 1
        if batch and batch_bytes + encoded_size > 32 * 1024:
            outputs.append(_run_macos_acl_batch(batch))
            batch = []
            batch_bytes = 0
        batch.append(value)
        batch_bytes += encoded_size
    if batch:
        outputs.append(_run_macos_acl_batch(batch))
    return b"\0--ACL-BATCH--\0".join(outputs)


def _run_macos_acl_batch(paths: list[str]) -> bytes:
    try:
        result = subprocess.run(
            ["/bin/ls", "-ldne", *paths],
            capture_output=True,
            timeout=15,
            check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise OSError(errno.EIO, f"cannot inspect macOS ACLs: {exc}") from exc
    if result.returncode != 0:
        raise OSError(
            errno.EIO,
            "cannot inspect macOS ACLs: "
            + result.stderr.decode("utf-8", errors="replace").strip(),
        )
    return result.stdout


def _tracked_paths(root: Path) -> list[Path] | None:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=str(root),
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return [
        root / value.decode("utf-8", errors="surrogateescape")
        for value in proc.stdout.split(b"\0")
        if value
    ]


def _tree_fingerprint(root: Path, *, tracked_only: bool = False) -> str | None:
    """Hash root plus tracked or all non-.git paths without following links."""

    try:
        digest = hashlib.sha256()
        selected = _tracked_paths(root) if tracked_only else list(root.rglob("*"))
        if selected is None:
            return None
        selected_paths = []
        for path in [root, *sorted(selected, key=lambda item: item.as_posix())]:
            relative = Path(".") if path == root else path.relative_to(root)
            if ".git" not in relative.parts:
                selected_paths.append(path)
        native_xattrs = _macos_xattr_snapshot(selected_paths)
        if native_xattrs is not None:
            digest.update(b"NATIVE-MACOS-XATTRS\0")
            digest.update(native_xattrs)
        native_acls = _macos_acl_snapshot(selected_paths)
        if native_acls is not None:
            digest.update(b"NATIVE-MACOS-ACLS\0")
            digest.update(native_acls)
        for path in selected_paths:
            relative = Path(".") if path == root else path.relative_to(root)
            metadata = path.lstat()
            digest.update(relative.as_posix().encode("utf-8", errors="surrogateescape"))
            digest.update(b"\0")
            for field in (
                "st_mode",
                "st_uid",
                "st_gid",
                "st_nlink",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
                "st_dev",
                "st_ino",
                "st_flags",
            ):
                digest.update(field.encode("ascii"))
                digest.update(b"=")
                digest.update(str(getattr(metadata, field, 0)).encode("ascii"))
                digest.update(b"\0")
            if native_xattrs is None:
                for name, value in _xattrs(path):
                    digest.update(name.encode("utf-8", errors="surrogateescape"))
                    digest.update(b"\0")
                    digest.update(value)
                    digest.update(b"\0")
            if stat.S_ISLNK(metadata.st_mode):
                digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
            elif stat.S_ISREG(metadata.st_mode):
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
        return digest.hexdigest()
    except (OSError, ValueError):
        return None


def _git_status(root: Path) -> bytes | None:
    """Capture worktree plus logical index content and per-path flags."""

    outputs = []
    for arguments in (
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
        ["ls-files", "--stage", "-z"],
        ["ls-files", "-v", "-z"],
    ):
        try:
            proc = subprocess.run(
                ["git", *arguments],
                cwd=str(root),
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if proc.returncode != 0:
            return None
        outputs.append(b"git " + b" ".join(arg.encode("utf-8") for arg in arguments) + b"\0" + proc.stdout)
    return b"\0--QUALIFICATION-GIT-STATE--\0".join(outputs)


def run_qualifications(
    settings_path: Path,
    config_root: Path,
    claude_command: str,
    *,
    full_tree: bool = False,
) -> list[QualificationResult]:
    results: list[QualificationResult] = []
    before_tree = _tree_fingerprint(config_root, tracked_only=not full_tree)
    before_status = _git_status(config_root)
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        if not isinstance(settings, dict):
            raise TypeError("settings root is not an object")
    except (OSError, ValueError, TypeError) as exc:
        return [QualificationResult("settings", False, f"{type(exc).__name__}: {exc}")]

    minimum = settings.get("minimumVersion", "")
    try:
        proc = subprocess.run(
            [claude_command, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        actual = proc.stdout.strip()
        ok = proc.returncode == 0 and version_at_least(actual, minimum)
        results.append(QualificationResult("version_floor", ok, f"installed={actual or 'unknown'} required={minimum or 'unset'}"))
    except (OSError, subprocess.SubprocessError) as exc:
        results.append(QualificationResult("version_floor", False, f"{type(exc).__name__}: {exc}"))

    static_problems = validate_static_contracts(
        settings,
        os.environ,
        config_root=config_root,
    )
    results.append(QualificationResult(
        "static_contracts",
        not static_problems,
        "hook exec, fresh worktree, and top-level identity are valid" if not static_problems else "; ".join(static_problems),
    ))

    with tempfile.TemporaryDirectory(prefix="claude-release-qualification-") as temporary:
        temp_dir = Path(temporary)
        results.append(qualify_session_end(settings, config_root, temp_dir / "receipts"))
        results.append(qualify_config_change(settings, config_root, temp_dir))

    after_tree = _tree_fingerprint(config_root, tracked_only=not full_tree)
    after_status = _git_status(config_root)
    clean = (
        before_tree is not None
        and after_tree is not None
        and before_status is not None
        and after_status is not None
        and before_tree == after_tree
        and before_status == after_status
    )
    results.append(QualificationResult(
        "repository_unchanged",
        clean,
        (
            "complete non-.git tree content, ownership, modes, BSD flags, ACLs, xattrs, root metadata, and logical Git index unchanged"
            if full_tree
            else "tracked source content, ownership, modes, BSD flags, ACLs, xattrs, root metadata, and logical Git index unchanged"
        )
        if clean else "qualification changed repository or the complete mutation evidence was unavailable",
    ))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, default=Path(__file__).resolve().parents[1] / "settings.json")
    parser.add_argument("--config-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--claude-command", default="claude")
    parser.add_argument(
        "--full-tree",
        action="store_true",
        help="also fingerprint ignored files; use on a quiescent isolated checkout",
    )
    parser.add_argument("--json", action="store_true", help="emit one JSON document")
    args = parser.parse_args(argv)

    results = run_qualifications(
        args.settings.resolve(),
        args.config_root.resolve(),
        args.claude_command,
        full_tree=args.full_tree,
    )
    if args.json:
        print(json.dumps({"ok": all(row.ok for row in results), "results": [row._asdict() for row in results]}, indent=2, sort_keys=True))
    else:
        for row in results:
            print(f"{'PASS' if row.ok else 'FAIL'} {row.name}: {row.detail}")
    return 0 if all(row.ok for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
