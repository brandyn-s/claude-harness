"""Tests for the non-billable Claude Code release qualification."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "bin" / "claude-release-qualification.py"
SPEC = importlib.util.spec_from_file_location("claude_release_qualification", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _settings(command="/absolute/hooks/run-hook", args=None):
    return {
        "minimumVersion": "2.1.223",
        "hooks": {
            "SessionEnd": [{"hooks": [{
                "type": "command",
                "command": command,
                "args": ["session-end.py"] if args is None else args,
            }]}]
        },
    }


def test_parse_version_ignores_cli_suffix():
    assert MODULE.parse_version("2.1.223 (Claude Code)") == (2, 1, 223)


def test_version_floor_accepts_newer_and_rejects_older():
    assert MODULE.version_at_least("2.1.223", "2.1.223")
    assert MODULE.version_at_least("2.1.224", "2.1.223")
    assert not MODULE.version_at_least("2.1.222", "2.1.223")


def test_find_registered_hook_uses_exec_form_args():
    hook = MODULE.find_registered_hook(
        _settings(), "SessionEnd", "session-end.py"
    )
    assert hook["command"] == "/absolute/hooks/run-hook"
    assert hook["args"] == ["session-end.py"]


def test_find_registered_hook_ignores_trailing_python_argument_identity():
    settings = _settings(args=["other-hook.py", "session-end.py"])
    settings["hooks"]["SessionEnd"][0]["hooks"].append(
        {
            "type": "command",
            "command": "/absolute/hooks/run-hook",
            "args": ["session-end.py", "payload.py"],
        }
    )

    hook = MODULE.find_registered_hook(settings, "SessionEnd", "session-end.py")

    assert hook["args"] == ["session-end.py", "payload.py"]


def test_exec_contract_rejects_shell_expansion_and_missing_args():
    settings = _settings('"$HOME/.claude/hooks/run-hook" session-end.py', [])
    problems = MODULE.validate_hook_exec_contract(settings)
    assert any("absolute" in problem for problem in problems)
    assert any("args" in problem for problem in problems)


@pytest.mark.parametrize(
    "command",
    [
        "/bin/bash /old/hooks/run-hook",
        "/bin/bash --noprofile /old/hooks/run-hook",
        "/usr/bin/env bash /old/hooks/run-hook",
        "/usr/bin/nohup /bin/bash /old/hooks/run-hook",
        "/usr/bin/sudo /bin/bash /old/hooks/run-hook",
        "/usr/bin/env -S 'bash /old/hooks/run-hook'",
        '"C:/Program Files/Git/bin/bash.exe" C:/Users/example/.claude/hooks/run-hook',
    ],
)
def test_exec_contract_rejects_dispatcher_argv_embedded_in_command(
    command, tmp_path
):
    settings = _settings(command, ["guard.py"])

    problems = MODULE.validate_hook_exec_contract(settings, config_root=tmp_path)

    assert any("embeds dispatcher argv" in problem for problem in problems)


def test_exec_contract_accepts_absolute_command_and_string_args():
    assert MODULE.validate_hook_exec_contract(_settings()) == []


def test_exec_contract_accepts_cross_host_absolute_path_spellings():
    assert MODULE.validate_hook_exec_contract(
        _settings("C:/Users/example/.claude/hooks/run-hook", ["session-end.py"])
    ) == []


def test_exec_contract_accepts_direct_hook_whose_name_contains_run_hook():
    settings = _settings("/old/hooks/pre-run-hook-guard.sh", [])

    assert MODULE.validate_hook_exec_contract(settings) == []


@pytest.mark.parametrize(
    ("command", "args"),
    [
        ("/old/hooks/run-hook", ["--not-a-script"]),
        ("/bin/bash", ["/old/hooks/run-hook"]),
    ],
)
def test_exec_contract_rejects_dispatcher_without_hook_target(command, args):
    settings = _settings(command, args)

    problems = MODULE.validate_hook_exec_contract(settings)

    assert any("must name a hook script" in problem for problem in problems)


@pytest.mark.parametrize(
    ("command", "args"),
    [
        ("/old/hooks/run-hook", ["../guard.py"]),
        ("/bin/bash", ["/old/hooks/run-hook", "../guard.py"]),
    ],
)
def test_exec_contract_rejects_dispatcher_target_path_traversal(command, args):
    settings = _settings(command, args)

    problems = MODULE.validate_hook_exec_contract(settings)

    assert any("unquoted basename" in problem for problem in problems)


@pytest.mark.parametrize(
    "args",
    [
        ["C:/old/hooks/run-hook"],
        ["C:/old/hooks/run-hook", "--mode", "guard.py"],
        ["C:/old/hooks/run-hook", "../guard.py"],
    ],
)
def test_exec_contract_validates_existing_program_files_bash(tmp_path, args):
    bash = tmp_path / "Program Files" / "Git" / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_text("#!/bin/sh\n", encoding="utf-8")
    settings = _settings(str(bash), args)

    problems = MODULE.validate_hook_exec_contract(settings)

    assert any("run-hook" in problem for problem in problems)


@pytest.mark.parametrize(
    ("command", "args"),
    [
        ("/old/hooks/run-hook", ["guard.sh"]),
        ("/bin/bash", ["/old/hooks/run-hook", "guard.sh"]),
    ],
)
def test_exec_contract_rejects_shell_script_target_through_python_dispatcher(
    command, args
):
    settings = _settings(command, args)

    problems = MODULE.validate_hook_exec_contract(settings)

    assert any("Python hook" in problem for problem in problems)


def test_exec_contract_accepts_literal_shell_looking_exec_form_args():
    settings = _settings(
        "/absolute/hooks/run-hook",
        ["session-end.py", "$HOME/payload", "^(a|b)$", "alpha#beta"],
    )

    assert MODULE.validate_hook_exec_contract(settings) == []


@pytest.mark.parametrize("value", ["line\nbreak", "carriage\rreturn", "nul\x00byte"])
def test_exec_contract_rejects_control_characters_in_args(value):
    settings = _settings(
        "/absolute/hooks/run-hook",
        ["session-end.py", value],
    )

    problems = MODULE.validate_hook_exec_contract(settings)

    assert any("NUL or line breaks" in problem for problem in problems)


def test_exec_contract_rejects_missing_non_qualification_dispatcher(tmp_path):
    settings = _settings(str(tmp_path / "missing" / "run-hook"))

    problems = MODULE.validate_hook_exec_contract(settings, config_root=tmp_path)

    assert any("does not exist" in problem for problem in problems)


def test_exec_contract_validates_only_positional_hook_identity(tmp_path):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    for name in ("run-hook", "guard.py"):
        target = hooks / name
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(0o755)
    settings = {
        "hooks": {
            "PreToolUse": [{
                "hooks": [{
                    "type": "command",
                    "command": "/old/hooks/run-hook",
                    "args": ["guard.py", "payload.py"],
                }]
            }]
        }
    }

    problems = MODULE.validate_hook_exec_contract(settings, config_root=tmp_path)

    assert problems == []


def test_exec_contract_does_not_treat_direct_hook_payload_as_dispatcher(tmp_path):
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    guard = hooks / "guard.sh"
    guard.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    guard.chmod(0o755)
    settings = {
        "hooks": {
            "PreToolUse": [{
                "hooks": [{
                    "type": "command",
                    "command": "/old/hooks/guard.sh",
                    "args": ["/data/run-hook", "payload.py"],
                }]
            }]
        }
    }

    assert MODULE.validate_hook_exec_contract(settings, config_root=tmp_path) == []


def test_static_contracts_require_fresh_worktree_and_no_child_marker(monkeypatch):
    settings = _settings()
    settings["worktree"] = {"baseRef": "stale"}
    monkeypatch.setenv("CLAUDE_CODE_CHILD_SESSION", "1")

    problems = MODULE.validate_static_contracts(settings, os.environ)

    assert any("worktree.baseRef" in problem for problem in problems)
    assert any("CHILD_SESSION" in problem for problem in problems)


def test_static_contracts_reject_child_marker_in_configured_env():
    settings = _settings()
    settings["worktree"] = {"baseRef": "fresh"}
    settings["env"] = {"CLAUDE_CODE_CHILD_SESSION": "1"}

    problems = MODULE.validate_static_contracts(settings, {})

    assert any("CHILD_SESSION" in problem for problem in problems)


def test_runtime_hook_path_uses_candidate_root_not_deployed_command(tmp_path):
    hook = _settings()["hooks"]["SessionEnd"][0]["hooks"][0]
    expected = tmp_path / "hooks" / "run-hook"

    assert MODULE.runtime_hook_command(hook, tmp_path) == [
        str(expected),
        "session-end.py",
    ]


def test_runtime_hook_path_rejects_embedded_dispatcher_argv(tmp_path):
    hook = {
        "type": "command",
        "command": "/bin/bash /old/hooks/run-hook",
        "args": ["guard.py"],
    }

    with pytest.raises(ValueError, match="must not be remapped"):
        MODULE.runtime_hook_command(hook, tmp_path)


@pytest.mark.parametrize(
    "command",
    [
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
def test_exec_contract_rejects_wrapped_structured_hook_commands(command):
    problems = MODULE.validate_hook_exec_contract(_settings(command, []))

    assert any("structured exec form" in problem for problem in problems)


@pytest.mark.parametrize(
    ("command", "args"),
    [
        ("/usr/bin/logger", ["guard.py"]),
        ("/usr/bin/printf", ["payload.py", "guard.py"]),
        ("/usr/bin/env", ["guard.py"]),
    ],
)
def test_exec_contract_does_not_treat_payload_script_as_identity(command, args):
    settings = _settings(command, args)

    assert MODULE.validate_hook_exec_contract(settings) == []
    with pytest.raises(LookupError):
        MODULE.find_registered_hook(settings, "SessionEnd", "guard.py")


def test_runtime_hook_path_remaps_windows_bash_registration(tmp_path):
    bash = tmp_path / "Program Files" / "Git" / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_text("#!/bin/sh\n", encoding="utf-8")
    hook = {
        "type": "command",
        "command": str(bash),
        "args": ["C:/Users/example/.claude/hooks/run-hook", "session-end.py"],
    }

    assert MODULE.runtime_hook_command(hook, tmp_path) == [
        str(bash),
        str(tmp_path / "hooks" / "run-hook"),
        "session-end.py",
    ]


def test_runtime_hook_path_keeps_direct_hook_payload_named_run_hook(tmp_path):
    hook = {
        "type": "command",
        "command": "/old/hooks/guard.sh",
        "args": ["/data/run-hook", "payload.py"],
    }

    assert MODULE.runtime_hook_command(hook, tmp_path) == [
        "/old/hooks/guard.sh",
        "/data/run-hook",
        "payload.py",
    ]


def test_runtime_hook_path_normalizes_windows_candidate_root(tmp_path):
    bash = tmp_path / "Program Files" / "Git" / "bin" / "bash.exe"
    bash.parent.mkdir(parents=True)
    bash.write_text("#!/bin/sh\n", encoding="utf-8")
    hook = {
        "type": "command",
        "command": str(bash),
        "args": ["C:/Users/example/.claude/hooks/run-hook", "session-end.py"],
    }

    command = MODULE.runtime_hook_command(
        hook, PureWindowsPath(r"D:\candidate\.claude")
    )

    assert command[1] == "D:/candidate/.claude/hooks/run-hook"
    assert "\\" not in command[1]


def test_session_end_qualification_runs_without_home_and_writes_receipt(tmp_path):
    settings = _settings()
    before = MODULE._tree_fingerprint(REPO)
    result = MODULE.qualify_session_end(settings, REPO, tmp_path)
    after = MODULE._tree_fingerprint(REPO)

    assert result.ok, result.detail
    receipt = json.loads((tmp_path / "release-qualification.json").read_text())
    assert receipt["session_id"] == "release-qualification"
    assert before == after, "SessionEnd qualification must not write telemetry into the candidate"


@pytest.mark.skipif(
    not (REPO / "hooks" / "config-change-validate.py").is_file(),
    reason="config-integrity branch is integrated only in the final qualification tree",
)
def test_config_change_qualification_blocks_invalid_user_settings(tmp_path):
    settings = _settings()
    settings["hooks"]["ConfigChange"] = [{
        "matcher": "user_settings|project_settings|local_settings",
        "hooks": [{
            "type": "command",
            "command": "/absolute/hooks/run-hook",
            "args": ["config-change-validate.py"],
            "timeout": 30,
        }],
    }]

    result = MODULE.qualify_config_change(settings, REPO, tmp_path)

    assert result.ok, result.detail


def test_config_change_qualification_requires_exact_matcher_and_timeout(tmp_path):
    for matcher, timeout in (
        ("user_settings|project_settings", 30),
        ("user_settings | project_settings | local_settings", 30),
        ("user_settings|project_settings|local_settings", 1),
    ):
        settings = _settings()
        settings["hooks"]["ConfigChange"] = [{
            "matcher": matcher,
            "hooks": [{
                "type": "command",
                "command": "/absolute/hooks/run-hook",
                "args": ["config-change-validate.py"],
                "timeout": timeout,
            }],
        }]

        result = MODULE.qualify_config_change(settings, REPO, tmp_path)

        assert not result.ok


def test_config_change_qualification_exercises_every_mutable_settings_source(tmp_path, monkeypatch):
    settings = _settings()
    settings["hooks"]["ConfigChange"] = [{
        "matcher": "user_settings|project_settings|local_settings",
        "hooks": [{
            "type": "command",
            "command": "/absolute/hooks/run-hook",
            "args": ["config-change-validate.py"],
            "timeout": 30,
        }],
    }]
    seen = []

    def fake_run(_command, payload, _env, _cwd):
        seen.append(payload["source"])
        stdout = (
            json.dumps({"decision": "block"})
            if payload["source"] != "policy_settings"
            else ""
        )
        return subprocess.CompletedProcess([], 0, stdout, "")

    monkeypatch.setattr(MODULE, "_run_hook", fake_run)

    result = MODULE.qualify_config_change(settings, REPO, tmp_path)

    assert result.ok, result.detail
    assert seen == [
        "user_settings",
        "project_settings",
        "local_settings",
        "policy_settings",
    ]


@pytest.mark.parametrize("child_marker", [None, "1"])
def test_branch_local_materialized_candidate_passes_complete_qualification(
    tmp_path, child_marker
):
    """End-to-end qualification of a materialized candidate, both env polarities.

    The subprocess env is built EXPLICITLY rather than inherited. Claude Code
    exports CLAUDE_CODE_CHILD_SESSION=1 into the Bash-tool environment (recorded
    in docs/PLATFORM_NOTES.md under #67603), so an inherited env made this test
    represent a CHILD invocation while asserting the contract for a TOP-LEVEL
    one -- static_contracts failed with "top-level environment unexpectedly sets
    CLAUDE_CODE_CHILD_SESSION" on every run started from inside a session, which
    is the only way we ever run it.

    child_marker=None is the top-level scenario the test name describes.
    child_marker="1" is the negative control: scrubbing the variable would
    otherwise leave this condition UNCHECKED in the end-to-end path, so the
    fix would trade a false failure for a blind spot.
    """
    candidate = tmp_path / "candidate"
    hooks = candidate / "hooks"
    hooks.mkdir(parents=True)
    for name in ("run-hook", "session-end.py", "session_runtime.py", "atomic_write.py"):
        shutil.copy2(REPO / "hooks" / name, hooks / name)
    (hooks / "run-hook").chmod(0o755)
    settings = candidate / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "minimumVersion": "2.1.223",
                "worktree": {"baseRef": "fresh"},
                "hooks": {
                    "SessionEnd": [{
                        "hooks": [{
                            "type": "command",
                            "command": "/old/hooks/run-hook",
                            "args": ["session-end.py"],
                        }]
                    }],
                    "ConfigChange": [{
                        "matcher": "user_settings|project_settings|local_settings",
                        "hooks": [{
                            "type": "command",
                            "command": "/old/hooks/run-hook",
                            "args": ["config-change-validate.py"],
                            "timeout": 30,
                        }],
                    }],
                },
            }
        ),
        encoding="utf-8",
    )

    materialized = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "materialize_release_candidate.py"),
            str(candidate),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert materialized.returncode == 0, materialized.stderr
    assert (hooks / "config-change-validate.py").is_file()
    candidate_bin = candidate / "bin"
    candidate_scripts = candidate / "scripts"
    candidate_bin.mkdir(exist_ok=True)
    candidate_scripts.mkdir(exist_ok=True)
    shutil.copy2(SCRIPT, candidate_bin / SCRIPT.name)
    shutil.copy2(
        REPO / "scripts" / "hook_exec_form.py",
        candidate_scripts / "hook_exec_form.py",
    )

    subprocess.run(["git", "init", "-q"], cwd=candidate, check=True)
    subprocess.run(
        ["git", "config", "user.email", "qualification@example.invalid"],
        cwd=candidate,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Qualification"], cwd=candidate, check=True
    )
    subprocess.run(["git", "add", "."], cwd=candidate, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=candidate, check=True)
    claude = tmp_path / "claude"
    claude.write_text("#!/bin/sh\necho '2.1.223 (Claude Code)'\n", encoding="utf-8")
    claude.chmod(0o755)

    env = dict(os.environ)
    env.pop("CLAUDE_CODE_CHILD_SESSION", None)
    if child_marker is not None:
        env["CLAUDE_CODE_CHILD_SESSION"] = child_marker

    result = subprocess.run(
        [
            sys.executable,
            str(candidate_bin / SCRIPT.name),
            "--settings",
            str(settings),
            "--config-root",
            str(candidate),
            "--claude-command",
            str(claude),
            "--full-tree",
            "--json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
        env=env,
    )
    payload = json.loads(result.stdout)
    static = next(r for r in payload["results"] if r["name"] == "static_contracts")

    if child_marker is None:
        assert result.returncode == 0, payload
        assert payload["ok"] is True
    else:
        # Negative control: the child marker must still be rejected end-to-end,
        # and specifically by static_contracts -- not merely produce some
        # nonzero exit for an unrelated reason.
        assert result.returncode != 0, payload
        assert payload["ok"] is False
        assert static["ok"] is False, payload
        assert "CLAUDE_CODE_CHILD_SESSION" in static["detail"]

    # Byproduct assertions hold in BOTH polarities: qualification must never
    # leave bytecode behind in the candidate tree, pass or fail.
    assert not list(candidate.rglob("__pycache__"))
    assert not list(candidate.rglob("*.pyc"))


def test_tree_fingerprint_detects_ignored_file_mutation(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "volatile").write_text("ignored metadata", encoding="utf-8")
    (tmp_path / ".gitignore").write_text("audit/\n", encoding="utf-8")
    before = MODULE._tree_fingerprint(tmp_path)
    audit = tmp_path / "audit"
    audit.mkdir()
    (audit / "hook-fire.jsonl").write_text("new ignored evidence", encoding="utf-8")

    after = MODULE._tree_fingerprint(tmp_path)

    assert before != after


def test_tree_fingerprint_detects_permission_only_mutation(tmp_path):
    script = tmp_path / "hook"
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    script.chmod(0o644)
    before = MODULE._tree_fingerprint(tmp_path)
    script.chmod(0o755)

    after = MODULE._tree_fingerprint(tmp_path)

    assert before != after


def test_tree_fingerprint_detects_root_directory_mode_mutation(tmp_path):
    tmp_path.chmod(0o700)
    before = MODULE._tree_fingerprint(tmp_path)
    tmp_path.chmod(0o755)

    after = MODULE._tree_fingerprint(tmp_path)

    assert before != after


def test_tree_fingerprint_detects_extended_attribute_mutation(tmp_path):
    if not hasattr(os, "setxattr"):
        pytest.skip("extended attributes are unavailable")
    target = tmp_path / "tracked.txt"
    target.write_text("stable", encoding="utf-8")
    before = MODULE._tree_fingerprint(tmp_path)
    try:
        os.setxattr(target, "user.claude_qualification", b"changed")
    except OSError as exc:
        pytest.skip(f"filesystem does not support test xattrs: {exc}")

    after = MODULE._tree_fingerprint(tmp_path)

    assert before != after


@pytest.mark.skipif(sys.platform != "darwin", reason="native macOS xattr contract")
def test_tree_fingerprint_detects_macos_xattr_without_python_xattr_api(tmp_path, monkeypatch):
    target = tmp_path / "tracked.txt"
    target.write_text("stable", encoding="utf-8")
    monkeypatch.delattr(MODULE.os, "listxattr", raising=False)
    monkeypatch.delattr(MODULE.os, "getxattr", raising=False)
    before = MODULE._tree_fingerprint(tmp_path)

    subprocess.run(
        [
            "/usr/bin/xattr",
            "-w",
            "com.example.claude-release-qualification",
            "changed",
            str(target),
        ],
        check=True,
    )
    after = MODULE._tree_fingerprint(tmp_path)

    assert before != after


@pytest.mark.skipif(sys.platform != "darwin", reason="native macOS ACL contract")
def test_tree_fingerprint_detects_macos_acl_mutation(tmp_path):
    target = tmp_path / "tracked.txt"
    target.write_text("stable", encoding="utf-8")
    before = MODULE._tree_fingerprint(tmp_path)
    user = subprocess.run(
        ["/usr/bin/id", "-un"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    subprocess.run(
        ["/bin/chmod", "+a", f"{user} allow read,write", str(target)],
        check=True,
    )
    after = MODULE._tree_fingerprint(tmp_path)

    assert before != after


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS BSD flags contract")
def test_tree_fingerprint_detects_macos_bsd_flag_mutation(tmp_path):
    target = tmp_path / "tracked.txt"
    target.write_text("stable", encoding="utf-8")
    before = MODULE._tree_fingerprint(tmp_path)

    subprocess.run(["/usr/bin/chflags", "hidden", str(target)], check=True)
    after = MODULE._tree_fingerprint(tmp_path)

    assert before != after


def test_tree_fingerprint_detects_ownership_mutation_when_permitted(tmp_path):
    if not hasattr(os, "getgroups") or not hasattr(os, "chown"):
        pytest.skip("ownership mutation APIs are unavailable")
    target = tmp_path / "tracked.txt"
    target.write_text("stable", encoding="utf-8")
    current_gid = target.lstat().st_gid
    alternate_gid = next((gid for gid in os.getgroups() if gid != current_gid), None)
    if alternate_gid is None:
        pytest.skip("no alternate permitted group is available")
    before = MODULE._tree_fingerprint(tmp_path)
    try:
        os.chown(target, -1, alternate_gid)
    except PermissionError as exc:
        pytest.skip(f"group ownership mutation is not permitted: {exc}")

    after = MODULE._tree_fingerprint(tmp_path)

    assert before != after


@pytest.mark.skipif(sys.platform != "darwin", reason="native macOS xattr contract")
def test_tree_fingerprint_excludes_git_metadata_from_native_xattrs(tmp_path, monkeypatch):
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    head = git_dir / "HEAD"
    head.write_text("ref: refs/heads/main\n", encoding="utf-8")
    (tmp_path / "tracked.txt").write_text("stable", encoding="utf-8")
    monkeypatch.delattr(MODULE.os, "listxattr", raising=False)
    monkeypatch.delattr(MODULE.os, "getxattr", raising=False)
    before = MODULE._tree_fingerprint(tmp_path)

    subprocess.run(
        [
            "/usr/bin/xattr",
            "-w",
            "com.example.claude-release-qualification",
            "git-only-change",
            str(head),
        ],
        check=True,
    )
    after = MODULE._tree_fingerprint(tmp_path)

    assert before == after


def test_git_state_detects_assume_unchanged_index_flag(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "qualification@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Qualification"], cwd=repo, check=True)
    (repo / "tracked.txt").write_text("stable\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=repo, check=True)
    before = MODULE._git_status(repo)

    subprocess.run(
        ["git", "update-index", "--assume-unchanged", "tracked.txt"],
        cwd=repo,
        check=True,
    )
    after = MODULE._git_status(repo)

    assert before != after


def test_tree_fingerprint_detects_mtime_only_mutation(tmp_path):
    candidate = tmp_path / "candidate"
    candidate.write_text("unchanged", encoding="utf-8")
    before = MODULE._tree_fingerprint(tmp_path)
    metadata = candidate.stat()
    os.utime(candidate, ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000))

    after = MODULE._tree_fingerprint(tmp_path)

    assert before != after


def test_git_status_detects_index_only_mutation(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    tracked = tmp_path / "candidate.txt"
    tracked.write_text("candidate\n", encoding="utf-8")
    before = MODULE._git_status(tmp_path)
    subprocess.run(["git", "add", "candidate.txt"], cwd=tmp_path, check=True)

    after = MODULE._git_status(tmp_path)

    assert before != after
