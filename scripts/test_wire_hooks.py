"""Tests for portable installer hook wiring."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest
from hook_exec_form import configured_hook_script, hook_exec_argv
from wire_hooks import wire_hooks


def test_posix_exec_form_runs_dispatcher_directly():
    command, args = hook_exec_argv(
        PurePosixPath("/Users/example/.claude"), "guard.py", native_windows=False
    )
    assert command == "/Users/example/.claude/hooks/run-hook"
    assert args == ["guard.py"]


def test_windows_exec_form_runs_dispatcher_through_bash_exe(tmp_path):
    bash = tmp_path / "Git" / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_text("#!/bin/sh\necho MSYS_NT-10.0\n", encoding="utf-8")
    bash.chmod(0o755)
    command, args = hook_exec_argv(
        PureWindowsPath(r"C:\Users\example\.claude"),
        "guard.py",
        native_windows=True,
        bash_executable=str(bash),
    )
    assert command == str(bash)
    assert args == ["C:/Users/example/.claude/hooks/run-hook", "guard.py"]
    assert all("\\" not in value for value in [command, *args])


def test_windows_uses_portable_git_environment_path(tmp_path, monkeypatch):
    bash = tmp_path / "Portable Git" / "bash.exe"
    bash.parent.mkdir()
    bash.write_text("#!/bin/sh\necho MINGW64_NT-10.0\n", encoding="utf-8")
    bash.chmod(0o755)
    monkeypatch.setenv("CLAUDE_CODE_GIT_BASH_PATH", str(bash))
    monkeypatch.setattr("hook_exec_form.shutil.which", lambda _name: None)

    command, args = hook_exec_argv(
        PureWindowsPath(r"C:\Users\example\.claude"),
        "guard.py",
        native_windows=True,
    )

    assert command == str(bash).replace("\\", "/")
    assert args[-1] == "guard.py"


def test_windows_without_git_bash_fails_loudly(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_GIT_BASH_PATH", raising=False)
    monkeypatch.setattr("hook_exec_form.shutil.which", lambda _name: None)
    try:
        hook_exec_argv(
            PureWindowsPath(r"C:\Users\example\.claude"),
            "guard.py",
            native_windows=True,
        )
    except RuntimeError as exc:
        assert "bash.exe was not found" in str(exc)
    else:
        raise AssertionError("native Windows wiring must not emit an inert .sh command")


def test_windows_rejects_wsl_bash_identity(tmp_path):
    bash = tmp_path / "bash.exe"
    bash.write_text("#!/bin/sh\necho Linux\n", encoding="utf-8")
    bash.chmod(0o755)

    try:
        hook_exec_argv(
            PureWindowsPath(r"C:\Users\example\.claude"),
            "guard.py",
            native_windows=True,
            bash_executable=str(bash),
        )
    except RuntimeError as exc:
        assert "not Git Bash" in str(exc) or "not found or validated" in str(exc)
    else:
        raise AssertionError("WSL bash.exe must not be accepted as Git Bash")


def test_wire_hooks_preserves_matcher_and_avoids_duplicates(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{}\n", encoding="utf-8")
    spec = "PreToolUse|Bash|guard.py|30"

    assert wire_hooks(settings, [spec]) == 1
    assert wire_hooks(settings, [spec]) == 0

    data = json.loads(settings.read_text(encoding="utf-8"))
    group = data["hooks"]["PreToolUse"][0]
    hook = group["hooks"][0]
    assert group["matcher"] == "Bash"
    assert configured_hook_script(hook) == "guard.py"
    assert hook["timeout"] == 30
    assert data["minimumVersion"] == "2.1.223"


def test_wire_hooks_preserves_logical_config_parent_for_symlinked_settings(tmp_path):
    logical_config = tmp_path / "home" / ".claude"
    logical_config.mkdir(parents=True)
    physical_config = tmp_path / "dotfiles"
    physical_config.mkdir()
    physical_settings = physical_config / "settings.json"
    physical_settings.write_text("{}\n", encoding="utf-8")
    logical_settings = logical_config / "settings.json"
    logical_settings.symlink_to(physical_settings)

    wire_hooks(logical_settings, ["PreToolUse|Bash|guard.py|30"])

    assert logical_settings.is_symlink()
    data = json.loads(physical_settings.read_text(encoding="utf-8"))
    hook = data["hooks"]["PreToolUse"][0]["hooks"][0]
    assert hook["command"] == str(logical_config / "hooks" / "run-hook")
    assert hook["args"] == ["guard.py"]


def test_wire_hooks_never_lowers_a_newer_minimum_version(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{"minimumVersion":"2.2.0"}\n', encoding="utf-8")

    assert wire_hooks(settings, ["PreToolUse|Bash|guard.py|30"]) == 1

    assert json.loads(settings.read_text(encoding="utf-8"))["minimumVersion"] == "2.2.0"


def test_wire_hooks_can_raise_only_the_minimum_version(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{}\n', encoding="utf-8")

    assert wire_hooks(settings, []) == 0

    assert json.loads(settings.read_text(encoding="utf-8")) == {
        "minimumVersion": "2.1.223"
    }


def test_cli_accepts_explicit_minimum_version_only_mode(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text('{}\n', encoding="utf-8")
    helper = Path(__file__).with_name("wire_hooks.py")

    result = subprocess.run(
        [sys.executable, str(helper), "--ensure-minimum-version", str(settings)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(settings.read_text(encoding="utf-8"))["minimumVersion"] == "2.1.223"


def test_wire_hooks_does_not_treat_another_matcher_as_coverage(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Write",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/absolute/hooks/run-hook",
                                    "args": ["guard.py"],
                                    "timeout": 30,
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    assert wire_hooks(settings, ["PreToolUse|Bash|guard.py|30"]) == 1

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert {group.get("matcher") for group in data["hooks"]["PreToolUse"]} == {
        "Write",
        "Bash",
    }


def test_wire_hooks_reconciles_exact_registration_timeout_and_exec_form(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/old/hooks/run-hook guard.py",
                                    "timeout": 5,
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    assert wire_hooks(settings, ["PreToolUse|Bash|guard.py|30"]) == 0

    hook = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]
    assert hook["timeout"] == 30
    assert hook["args"] == ["guard.py"]
    assert hook["command"].endswith("/hooks/run-hook")


def test_concurrent_wire_hooks_preserve_every_registration(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{}\n", encoding="utf-8")
    specs = [f"PreToolUse|Bash|guard-{index}.py|30" for index in range(12)]

    with ThreadPoolExecutor(max_workers=len(specs)) as pool:
        results = list(pool.map(lambda spec: wire_hooks(settings, [spec]), specs))

    assert results == [1] * len(specs)
    data = json.loads(settings.read_text(encoding="utf-8"))
    scripts = {
        configured_hook_script(handler)
        for group in data["hooks"]["PreToolUse"]
        for handler in group["hooks"]
    }
    assert scripts == {f"guard-{index}.py" for index in range(12)}


def test_cross_process_wire_hooks_preserve_every_registration(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{}\n", encoding="utf-8")
    helper = Path(__file__).with_name("wire_hooks.py")
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                str(helper),
                str(settings),
                f"PreToolUse|Bash|process-{index}.py|30",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for index in range(8)
    ]
    results = [process.communicate(timeout=30) for process in processes]
    assert [process.returncode for process in processes] == [0] * len(processes), results

    data = json.loads(settings.read_text(encoding="utf-8"))
    scripts = {
        configured_hook_script(handler)
        for group in data["hooks"]["PreToolUse"]
        for handler in group["hooks"]
    }
    assert scripts == {f"process-{index}.py" for index in range(8)}


def test_atomic_publish_preserves_mode(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{}\n", encoding="utf-8")
    settings.chmod(0o640)

    wire_hooks(settings, ["PreToolUse|Bash|guard.py|30"])

    assert settings.stat().st_mode & 0o777 == 0o640


def test_atomic_publish_preserves_extended_attributes_when_supported(tmp_path):
    if not all(hasattr(os, name) for name in ("setxattr", "getxattr")):
        return
    settings = tmp_path / "settings.json"
    settings.write_text("{}\n", encoding="utf-8")
    attribute = "user.claude-wire-hooks-test"
    try:
        os.setxattr(settings, attribute, b"preserve-me")
    except OSError:
        return

    wire_hooks(settings, ["PreToolUse|Bash|guard.py|30"])

    assert os.getxattr(settings, attribute) == b"preserve-me"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS ACL contract")
def test_atomic_publish_preserves_macos_acl(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text("{}\n", encoding="utf-8")
    identity = subprocess.run(
        ["id", "-un"], capture_output=True, text=True, check=True
    ).stdout.strip()
    subprocess.run(
        ["chmod", "+a", f"{identity} allow read,write", str(settings)],
        check=True,
    )

    before = subprocess.run(
        ["/bin/ls", "-lde", str(settings)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()[1:]
    assert before

    wire_hooks(settings, ["PreToolUse|Bash|guard.py|30"])

    after = subprocess.run(
        ["/bin/ls", "-lde", str(settings)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()[1:]
    assert after == before


def test_atomic_publish_refuses_noncooperating_writer(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text("{}\n", encoding="utf-8")
    real_fsync = os.fsync
    injected = False

    def inject_external_change(descriptor):
        nonlocal injected
        real_fsync(descriptor)
        if not injected:
            injected = True
            settings.write_text('{"external": true}\n', encoding="utf-8")

    monkeypatch.setattr("wire_hooks.os.fsync", inject_external_change)

    try:
        wire_hooks(settings, ["PreToolUse|Bash|guard.py|30"])
    except RuntimeError as exc:
        assert "changed concurrently" in str(exc)
    else:
        raise AssertionError("a noncooperating settings writer must stop publication")
    assert json.loads(settings.read_text(encoding="utf-8")) == {"external": True}


def test_atomic_publish_refuses_noncooperating_metadata_change(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text("{}\n", encoding="utf-8")
    settings.chmod(0o600)
    real_fsync = os.fsync
    injected = False

    def inject_external_change(descriptor):
        nonlocal injected
        real_fsync(descriptor)
        if not injected:
            injected = True
            settings.chmod(0o640)

    monkeypatch.setattr("wire_hooks.os.fsync", inject_external_change)

    try:
        wire_hooks(settings, ["PreToolUse|Bash|guard.py|30"])
    except RuntimeError as exc:
        assert "changed concurrently" in str(exc)
    else:
        raise AssertionError("a noncooperating metadata writer must stop publication")
    assert settings.stat().st_mode & 0o777 == 0o640


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS ACL contract")
def test_atomic_publish_refuses_concurrent_macos_acl_change(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text("{}\n", encoding="utf-8")
    identity = subprocess.run(
        ["id", "-un"], capture_output=True, text=True, check=True
    ).stdout.strip()
    real_fsync = os.fsync
    injected = False

    # Hold the ordinary stat signature constant so this test proves the ACL
    # comparison itself, not the incidental ctime update caused by chmod.
    monkeypatch.setattr("wire_hooks._metadata_signature", lambda _value: (0,))

    def inject_external_acl(descriptor):
        nonlocal injected
        real_fsync(descriptor)
        if not injected:
            injected = True
            subprocess.run(
                ["chmod", "+a", f"{identity} allow read,write", str(settings)],
                check=True,
            )

    monkeypatch.setattr("wire_hooks.os.fsync", inject_external_acl)

    with pytest.raises(RuntimeError, match="changed concurrently"):
        wire_hooks(settings, ["PreToolUse|Bash|guard.py|30"])

    acl = subprocess.run(
        ["/bin/ls", "-lde", str(settings)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()[1:]
    assert acl, "the concurrent ACL must remain on the unpublished source"


def test_reconcile_existing_materializes_all_hooks_for_native_windows(tmp_path):
    config = tmp_path / ".claude"
    hooks = config / "hooks"
    hooks.mkdir(parents=True)
    for name in ("run-hook", "guard.py", "orientation.sh"):
        target = hooks / name
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(0o755)
    bash = tmp_path / "Git" / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_text("#!/bin/sh\necho MINGW64_NT-10.0\n", encoding="utf-8")
    bash.chmod(0o755)
    settings = config / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/Users/old/.claude/hooks/run-hook",
                                    "args": ["guard.py"],
                                },
                                {
                                    "type": "command",
                                    "command": "/Users/old/.claude/hooks/orientation.sh",
                                    "args": [],
                                },
                            ],
                        }
                    ],
                    "Notification": [
                        {
                            "matcher": "idle_prompt",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/usr/bin/afplay",
                                    "args": ["/System/Library/Sounds/Glass.aiff"],
                                }
                            ],
                        }
                    ],
                },
                "statusLine": {
                    "type": "command",
                    "command": "/Users/old/.claude/bin/statusline-launcher",
                },
            }
        ),
        encoding="utf-8",
    )

    wire_hooks(
        settings,
        [],
        reconcile_existing=True,
        native_windows=True,
        platform_name="win32",
        bash_executable=str(bash),
    )

    data = json.loads(settings.read_text(encoding="utf-8"))
    handlers = data["hooks"]["PreToolUse"][0]["hooks"]
    assert handlers[0]["command"] == str(bash)
    assert handlers[0]["args"] == [
        str(hooks / "run-hook"),
        "guard.py",
    ]
    assert handlers[1]["command"] == str(bash)
    assert handlers[1]["args"] == [str(hooks / "orientation.sh")]
    assert "Notification" not in data["hooks"]
    assert "statusLine" not in data


def test_reconcile_existing_preserves_native_windows_trailing_arguments(tmp_path):
    config = tmp_path / ".claude"
    hooks = config / "hooks"
    hooks.mkdir(parents=True)
    for name in ("run-hook", "guard.py"):
        target = hooks / name
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(0o755)
    bash = tmp_path / "Git" / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_text("#!/bin/sh\necho MINGW64_NT-10.0\n", encoding="utf-8")
    bash.chmod(0o755)
    settings = config / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [{
                        "hooks": [{
                            "type": "command",
                            "command": "C:/old/Git/bin/bash.exe",
                            "args": [
                                "C:/old/.claude/hooks/run-hook",
                                "guard.py",
                                "--mode",
                                "strict",
                                "payload.py",
                            ],
                        }]
                    }]
                }
            }
        ),
        encoding="utf-8",
    )

    wire_hooks(
        settings,
        [],
        reconcile_existing=True,
        native_windows=True,
        platform_name="win32",
        bash_executable=str(bash),
    )

    hook = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]
    assert hook["command"] == str(bash)
    assert hook["args"] == [
        str(hooks / "run-hook"),
        "guard.py",
        "--mode",
        "strict",
        "payload.py",
    ]


def test_reconcile_existing_migrates_quoted_legacy_windows_dispatcher(tmp_path):
    config = tmp_path / ".claude"
    hooks = config / "hooks"
    hooks.mkdir(parents=True)
    for name in ("run-hook", "guard.py"):
        target = hooks / name
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(0o755)
    bash = tmp_path / "Git" / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_text("#!/bin/sh\necho MINGW64_NT-10.0\n", encoding="utf-8")
    bash.chmod(0o755)
    settings = config / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        '"C:\\Program Files\\Git\\bin\\bash.exe" '
                                        '"C:\\Users\\First Last\\.claude\\hooks\\run-hook" '
                                        "guard.py --mode strict"
                                    ),
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    wire_hooks(
        settings,
        [],
        reconcile_existing=True,
        native_windows=True,
        platform_name="win32",
        bash_executable=str(bash),
    )

    hook = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0][
        "hooks"
    ][0]
    assert hook["command"] == str(bash)
    assert hook["args"] == [str(hooks / "run-hook"), "guard.py", "--mode", "strict"]


def test_reconcile_existing_migrates_legacy_posix_escaped_space_path(tmp_path):
    config = tmp_path / ".claude"
    hooks = config / "hooks"
    hooks.mkdir(parents=True)
    for name in ("run-hook", "guard.py"):
        target = hooks / name
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(0o755)
    settings = config / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "/Users/First\\ Last/.claude/hooks/run-hook "
                                        "guard.py --mode strict"
                                    ),
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    wire_hooks(
        settings,
        [],
        reconcile_existing=True,
        native_windows=False,
        platform_name="linux",
    )

    hook = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0][
        "hooks"
    ][0]
    assert hook["command"] == str(hooks / "run-hook")
    assert hook["args"] == ["guard.py", "--mode", "strict"]


def test_reconcile_existing_rewrites_shared_mac_path_for_current_posix_host(tmp_path):
    config = tmp_path / ".claude"
    hooks = config / "hooks"
    hooks.mkdir(parents=True)
    for name in ("run-hook", "guard.py"):
        target = hooks / name
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(0o755)
    settings = config / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "/Users/another/.claude/hooks/run-hook",
                                    "args": ["guard.py"],
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    wire_hooks(
        settings,
        [],
        reconcile_existing=True,
        native_windows=False,
        platform_name="linux",
    )

    hook = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]
    assert hook["command"] == str(hooks / "run-hook")
    assert hook["args"] == ["guard.py"]


def test_reconcile_existing_preserves_legacy_trailing_arguments_including_python_files(tmp_path):
    config = tmp_path / ".claude"
    hooks = config / "hooks"
    hooks.mkdir(parents=True)
    for name in ("run-hook", "guard.py"):
        target = hooks / name
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(0o755)
    settings = config / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [{
                        "hooks": [{
                            "type": "command",
                            "command": "python /old/hooks/guard.py --mode strict payload.py",
                        }]
                    }]
                }
            }
        ),
        encoding="utf-8",
    )

    wire_hooks(
        settings,
        [],
        reconcile_existing=True,
        native_windows=False,
        platform_name="linux",
    )

    hook = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]
    assert hook["command"] == str(hooks / "run-hook")
    assert hook["args"] == ["guard.py", "--mode", "strict", "payload.py"]


def test_reconcile_existing_preserves_quoted_literal_legacy_arguments(tmp_path):
    config = tmp_path / ".claude"
    hooks = config / "hooks"
    hooks.mkdir(parents=True)
    for name in ("run-hook", "guard.py"):
        target = hooks / name
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(0o755)
    settings = config / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "python /old/hooks/guard.py --label "
                                        "'alpha#beta' '$PAYLOAD' 'foo(bar)'"
                                    ),
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    wire_hooks(
        settings,
        [],
        reconcile_existing=True,
        native_windows=False,
        platform_name="linux",
    )

    hook = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0][
        "hooks"
    ][0]
    assert hook["args"] == [
        "guard.py",
        "--label",
        "alpha#beta",
        "$PAYLOAD",
        "foo(bar)",
    ]


def test_reconcile_existing_leaves_malformed_dispatcher_argv_unchanged(tmp_path):
    config = tmp_path / ".claude"
    hooks = config / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "guard.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    settings = config / "settings.json"
    handler = {
        "type": "command",
        "command": "/old/hooks/run-hook",
        "args": ["--mode", "guard.py"],
        "timeout": 30,
    }
    settings.write_text(
        json.dumps({"hooks": {"PreToolUse": [{"hooks": [handler]}]}}),
        encoding="utf-8",
    )

    wire_hooks(
        settings,
        [],
        reconcile_existing=True,
        native_windows=False,
        platform_name="linux",
    )

    written = json.loads(settings.read_text(encoding="utf-8"))
    assert written["hooks"]["PreToolUse"][0]["hooks"][0] == handler


@pytest.mark.parametrize(
    "command",
    [
        "/usr/bin/nohup /bin/bash /old/hooks/run-hook",
        "/usr/bin/sudo /bin/bash /old/hooks/run-hook",
        "/usr/bin/env -S 'bash /old/hooks/run-hook'",
        "/usr/bin/python /old/hooks/guard.py",
        "/usr/bin/env python /old/hooks/guard.py",
        "/bin/bash /old/hooks/guard.sh",
        "/usr/bin/nohup /other/bash",
        "/bin/echo C:/Program Files/Git/bin/bash.exe",
        "C:/Windows/System32/cmd.exe C:/Program Files/Git/bin/bash.exe",
        "C:/Windows/System32/cmd.exe Program Files/Git/bin/bash.exe",
        "C:/Tools/wrapper.ps1 Program Files/Git/bin/bash.exe",
        "/bin/true&/old/hooks/run-hook",
        "'/old/hooks/guard.py'",
    ],
)
def test_reconcile_existing_leaves_wrapped_structured_command_unchanged(
    tmp_path, command
):
    config = tmp_path / ".claude"
    hooks = config / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "guard.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    settings = config / "settings.json"
    handler = {"type": "command", "command": command, "args": ["guard.py"]}
    settings.write_text(
        json.dumps(
            {
                "minimumVersion": "2.1.223",
                "hooks": {"PreToolUse": [{"hooks": [handler]}]},
            }
        ),
        encoding="utf-8",
    )

    wire_hooks(settings, [], reconcile_existing=True, native_windows=False)

    written = json.loads(settings.read_text(encoding="utf-8"))
    assert written["hooks"]["PreToolUse"][0]["hooks"][0] == handler


@pytest.mark.parametrize(
    ("command", "args"),
    [
        ("/usr/bin/logger", ["guard.py"]),
        ("/usr/bin/printf", ["payload.py", "guard.py"]),
        ("/usr/bin/env", ["guard.py"]),
    ],
)
def test_reconcile_existing_leaves_payload_script_names_unchanged(
    tmp_path, command, args
):
    config = tmp_path / ".claude"
    hooks = config / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "guard.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    settings = config / "settings.json"
    handler = {"type": "command", "command": command, "args": args}
    settings.write_text(
        json.dumps(
            {
                "minimumVersion": "2.1.223",
                "hooks": {"PreToolUse": [{"hooks": [handler]}]},
            }
        ),
        encoding="utf-8",
    )

    wire_hooks(settings, [], reconcile_existing=True, native_windows=False)

    written = json.loads(settings.read_text(encoding="utf-8"))
    assert written["hooks"]["PreToolUse"][0]["hooks"][0] == handler


@pytest.mark.parametrize(
    "command",
    [
        'python "/old/hooks/guard.py --mode',
        'python /old/hooks/guard.py "unterminated',
        "false && python /old/hooks/guard.py --mode strict",
        "python /old/hooks/guard.py || true",
        "FOO=bar python /old/hooks/guard.py",
        "/usr/bin/env FOO=bar python /old/hooks/guard.py",
        "timeout 5 python /old/hooks/guard.py",
        "nice -n 10 python /old/hooks/guard.py",
        "python -B /old/hooks/guard.py --mode",
        "python /old/hooks/guard.py 2>/tmp/log",
        "/old/hooks/run-hook guard.py 2>/tmp/log",
        "python /old/hooks/guard.py $PAYLOAD",
        'python /old/hooks/guard.py --label "$PAYLOAD"',
        'python /old/hooks/guard.py --label "$(echo unsafe)"',
        'python /old/hooks/guard.py --label "`echo unsafe`"',
        "python /old/hooks/guard.py ~/payload",
        "/old/hooks/run-hook guard.py ~/payload",
        "python /old/hooks/guard.py |tee",
        "python /old/hooks/guard.py ;echo",
        "python /old/hooks/guard.py &&echo",
        "python /old/hooks/guard.py arg&",
        "python /old/hooks/guard.py # ignored",
        "python /old/hooks/guard.py\necho changed",
        "python /old/hooks/guard.py (echo changed)",
        "/old/hooks/run-hook guard.py (echo changed)",
        "python /old/hooks/guard.py foo(bar)",
        "/old/hooks/run-hook guard.sh",
        '"$HOME/.claude/hooks/run-hook" guard.sh',
        '"$PAYLOAD/run-hook" guard.py',
        '"${PAYLOAD}/run-hook" guard.py',
        "'$PAYLOAD/run-hook' guard.py",
        'python "${PAYLOAD}/guard.py"',
        "python '$PAYLOAD/guard.py'",
        "bash '$PAYLOAD/run-hook' guard.py",
        '"~/other/run-hook" guard.py',
        "'~/other/run-hook' guard.py",
        '"%PAYLOAD%\\run-hook" guard.py',
        '"%ProgramFiles(x86)%\\Git\\hooks\\run-hook" guard.py',
        '"%PROGRAM-FILES%\\Git\\hooks\\run-hook" guard.py',
        '"%Program Files%\\Git\\hooks\\run-hook" guard.py',
        '"%USERPROFILE%%HOME%\\.claude\\hooks\\run-hook" guard.py',
        '"%USERPROFILE%X\\.claude\\hooks\\run-hook" guard.py',
        (
            '"C:\\Program Files\\Git\\bin\\bash.exe" '
            '"C:\\old\\hooks\\run-hook" guard.py --label "%PAYLOAD%"'
        ),
        (
            '"C:\\old\\hooks\\run-hook" guard.py '
            '--label "%ProgramFiles(x86)%"'
        ),
        '"C:\\old\\hooks\\run-hook" guard.py \'x& calc\'',
        '"C:\\Python\\python.exe" "C:\\old\\hooks\\guard.py" \'x| calc\'',
        '"C:/Program Files/Git/bin/bash.exe" C:/old/hooks/run-hook guard.sh',
    ],
)
def test_reconcile_existing_leaves_unsafe_legacy_commands_unchanged(
    tmp_path, command
):
    config = tmp_path / ".claude"
    hooks = config / "hooks"
    hooks.mkdir(parents=True)
    for name in ("guard.py", "guard.sh"):
        (hooks / name).write_text("raise SystemExit(0)\n", encoding="utf-8")
    settings = config / "settings.json"
    handler = {"type": "command", "command": command}
    settings.write_text(
        json.dumps(
            {
                "minimumVersion": "2.1.223",
                "hooks": {"PreToolUse": [{"hooks": [handler]}]},
            }
        ),
        encoding="utf-8",
    )

    wire_hooks(settings, [], reconcile_existing=True, native_windows=False)

    written = json.loads(settings.read_text(encoding="utf-8"))
    assert written["hooks"]["PreToolUse"][0]["hooks"][0] == handler


@pytest.mark.parametrize(
    "args",
    [
        "payload.py",
        ["guard.py", {"bad": 1}, "payload.py"],
        ["guard.py", 7],
        ["guard.py", None],
    ],
)
def test_reconcile_existing_leaves_invalid_structured_args_unchanged(tmp_path, args):
    config = tmp_path / ".claude"
    hooks = config / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "guard.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
    settings = config / "settings.json"
    handler = {
        "type": "command",
        "command": "/old/hooks/run-hook",
        "args": args,
    }
    settings.write_text(
        json.dumps(
            {
                "minimumVersion": "2.1.223",
                "hooks": {"PreToolUse": [{"hooks": [handler]}]},
            }
        ),
        encoding="utf-8",
    )

    wire_hooks(settings, [], reconcile_existing=True, native_windows=False)

    written = json.loads(settings.read_text(encoding="utf-8"))
    assert written["hooks"]["PreToolUse"][0]["hooks"][0] == handler


def test_reconcile_and_rewire_same_hook_preserves_trailing_arguments(tmp_path):
    config = tmp_path / ".claude"
    hooks = config / "hooks"
    hooks.mkdir(parents=True)
    for name in ("run-hook", "guard.py"):
        target = hooks / name
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(0o755)
    settings = config / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [{
                        "hooks": [{
                            "type": "command",
                            "command": "python /old/hooks/guard.py --mode strict payload.py",
                            "timeout": 5,
                        }]
                    }]
                }
            }
        ),
        encoding="utf-8",
    )

    assert wire_hooks(
        settings,
        ["PreToolUse||guard.py|30"],
        reconcile_existing=True,
        native_windows=False,
        platform_name="linux",
    ) == 0

    hook = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]
    assert hook["command"] == str(hooks / "run-hook")
    assert hook["args"] == ["guard.py", "--mode", "strict", "payload.py"]
    assert hook["timeout"] == 30
