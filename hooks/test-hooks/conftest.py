"""Shared fixtures for hook smoke tests."""
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

# Test-vs-production provenance: mark every hook invocation from this suite
# so hooks that write PRODUCTION telemetry (audit logs, query logs) can
# skip it. The 2026-06-12 Fable 5 recurrence recompute found
# 21/21 bare-keyword entries in the production query log were this suite's
# fixtures — the instrument that guard keep/prune audits read had been
# contaminated by the guard's own tests. run_hook() inherits os.environ,
# so setting it here covers every subprocess invocation.
os.environ["CLAUDE_HOOK_TEST"] = "1"

# Same reason, second instrument: repo_sync writes a recovery pointer to
# ~/.claude/.last-auto-checkpoint.json, which a REAL session reads to recover
# work a parallel session-start checkpointed away. Measured 2026-08-15: a run of
# this suite replaced the live artifact with a pytest tmp repo path WHILE
# ~/.claude was wedged mid-rebase, destroying the pointer to the real
# checkpoint/<ts> branch during the very incident it exists to help recover
# from. Redirect it for the whole suite; a test that asserts on it reads this
# same variable.
os.environ.setdefault(
    "CLAUDE_LAST_CHECKPOINT_ARTIFACT",
    str(Path(tempfile.gettempdir()) / "claude-hook-tests-last-auto-checkpoint.json"),
)

# bash-security-guard's inline/heredoc encoding checks are scoped to Windows
# (2026-06-27: cp1252 is Windows-only; macOS/Linux open() defaults to UTF-8).
# Force them active here so their detection logic stays covered on this
# non-Windows CI host; a test that needs the macOS no-op overlays
# CLAUDE_ENCODING_GUARD_FORCE="0".
os.environ["CLAUDE_ENCODING_GUARD_FORCE"] = "1"
# The legacy guard suite characterizes the author-workstation compatibility
# profile. Fresh-laptop default tests override this with an explicit empty
# value and prove that only catastrophic checks remain enabled there.
# Assigned, not setdefault: the installed operator profile exports
# CLAUDE_BASH_POLICY_PACKS=delivery into every shell on the owner's machine, and
# setdefault let that ambient value win, silently changing what 18 guard tests
# exercised (2026-09-04). The suite's pack set is a contract, not a default.
os.environ["CLAUDE_BASH_POLICY_PACKS"] = "all"
# The org guard is configuration (review 2026-09-03); the guard tests keep the
# historical fixture org so their block/allow assertions are unchanged.
os.environ["CLAUDE_FORBIDDEN_GITHUB_ORGS"] = "example-technologies"  # assigned for the same reason

windows_only = pytest.mark.skipif(
    platform.system() != "Windows",
    reason="Requires Windows paths and local git repos",
)


# ── Sandbox probes ────────────────────────────────────────────────────
# Some dev environments (Claude Code remote sandbox) force commit signing
# through a custom server, breaking tests that create ad-hoc git repos. And
# uv-managed pytest venvs can have `sys.executable` pointing at an interpreter
# without pyyaml/openpyxl installed, so hooks fail to import. Both pass in CI
# (Ubuntu runners, shared python). Detect at session start and skip with a
# clear reason instead of leaving devs with 20 mystery failures.

def _can_create_signed_test_commits() -> bool:
    """True if `git commit` works in a throwaway repo with the current env.

    Forced signing servers that reject ad-hoc test commits will fail this
    probe — and any test that needs to build a fixture git history will fail
    for the same reason.
    """
    with tempfile.TemporaryDirectory() as td:
        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = "probe"
        env["GIT_AUTHOR_EMAIL"] = "probe@example.com"
        env["GIT_COMMITTER_NAME"] = "probe"
        env["GIT_COMMITTER_EMAIL"] = "probe@example.com"
        try:
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=td, check=True, env=env, timeout=5)
            subprocess.run(
                ["git", "commit", "-q", "--allow-empty", "-m", "probe"],
                cwd=td, check=True, env=env, timeout=5,
                capture_output=True,
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return False


def _sys_executable_has(module: str) -> bool:
    """True if `sys.executable -c 'import <module>'` succeeds.

    Tests that run hooks via subprocess use sys.executable; if that interpreter
    is a uv-managed pytest venv missing the hook's deps, the hook silently
    exits and the test sees empty output."""
    try:
        result = subprocess.run(
            [PYTHON, "-c", f"import {module}"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


# Cache probe results for the session — they're stable and not cheap to run.
_SANDBOX_GIT_OK = _can_create_signed_test_commits()
_SYS_EXEC_HAS_YAML = _sys_executable_has("yaml")
_SYS_EXEC_HAS_OPENPYXL = _sys_executable_has("openpyxl")


# Map test file basenames to the capability they require. Add to this list
# when introducing a new test that needs either git or a third-party module.
_NEEDS_GIT = {
    "test_index_staleness.py",
    "test_mcp_binary_staleness.py",
    "test_git_empty_push_guard.py",
    "test_git_destructive_checkout_guard.py",
    "test_repo_sync.py",
    "test_worktree_gc.py",
}
_NEEDS_GIT_PER_TEST = {
    "test_bash_security_guard.py::test_autofix_rebase_dirty_wraps_with_stash",
    "test_bash_security_guard.py::test_autofix_rebase_clean_noop",
    "test_bash_security_guard.py::test_autofix_rebase_already_stashed_noop",
    "test_bash_security_guard.py::test_autofix_rebase_continue_noop",
}
# Empty since skill-routing-hint left; keep the slot for the next yaml-importing hook test.
_NEEDS_YAML_IN_SYSEXEC: set[str] = set()
_NEEDS_OPENPYXL_IN_SYSEXEC = {
    "test_xlsx_to_md.py",
}


def pytest_collection_modifyitems(config, items):
    """Apply skip markers based on sandbox probes at session start."""
    git_skip = pytest.mark.skip(
        reason="Sandbox env rejects ad-hoc git commits (forced signing). Runs in CI."
    )
    yaml_skip = pytest.mark.skip(
        reason="sys.executable lacks pyyaml (uv venv isolation). Runs in CI."
    )
    openpyxl_skip = pytest.mark.skip(
        reason="sys.executable lacks openpyxl (uv venv isolation). Runs in CI."
    )

    for item in items:
        path_name = Path(str(item.fspath)).name
        item_id = f"{path_name}::{item.name}"

        if not _SANDBOX_GIT_OK and (path_name in _NEEDS_GIT or item_id in _NEEDS_GIT_PER_TEST):
            item.add_marker(git_skip)
        if not _SYS_EXEC_HAS_YAML and path_name in _NEEDS_YAML_IN_SYSEXEC:
            item.add_marker(yaml_skip)
        if not _SYS_EXEC_HAS_OPENPYXL and path_name in _NEEDS_OPENPYXL_IN_SYSEXEC:
            item.add_marker(openpyxl_skip)


def run_hook(hook_name: str, hook_input: dict, timeout: int = 10,
             env: dict | None = None) -> tuple[int, str, str]:
    """Invoke a hook script with JSON stdin, return (exit_code, stdout, stderr).

    ``env`` (optional) overlays the given keys onto a copy of the current
    environment — used by tests that need to point a hook at an isolated
    file (e.g. AUDIT_SKILL_ORACLE_TRACE for the Layer-D gate)."""
    hook_path = HOOKS_DIR / hook_name
    assert hook_path.exists(), f"Hook not found: {hook_path}"
    run_env = None
    if env:
        run_env = os.environ.copy()
        run_env.update(env)
    result = subprocess.run(
        [PYTHON, str(hook_path)],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
        cwd=str(HOOKS_DIR.parent),
        env=run_env,
    )
    return result.returncode, result.stdout, result.stderr


def make_bash_input(command: str, cwd: str = "") -> dict:
    """Build a PreToolUse:Bash hook input payload."""
    return {
        "tool_name": "Bash",
        "tool_input": {
            "command": command,
        },
        "cwd": cwd or str(Path.home()),
    }


def make_powershell_input(command: str, cwd: str = "") -> dict:
    """Build a PreToolUse:PowerShell hook input payload."""
    return {
        "tool_name": "PowerShell",
        "tool_input": {
            "command": command,
        },
        "cwd": cwd or str(Path.home()),
    }


def make_write_input(file_path: str, content: str = "") -> dict:
    """Build a PostToolUse:Write hook input payload."""
    return {
        "tool_name": "Write",
        "tool_input": {
            "file_path": file_path,
            "content": content,
        },
    }


def make_glob_input(pattern: str, path: str) -> dict:
    """Build a PreToolUse:Glob hook input payload."""
    return {
        "tool_name": "Glob",
        "tool_input": {"pattern": pattern, "path": path},
    }


def make_grep_input(pattern: str, path: str) -> dict:
    """Build a PreToolUse:Grep hook input payload."""
    return {
        "tool_name": "Grep",
        "tool_input": {"pattern": pattern, "path": path},
    }
