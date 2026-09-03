"""Generic crash-safety guard for all hooks.

Skill-standards mandates that every hook touching stdin or making a system
call MUST wrap its body so a crash exits 0 rather than blocking the matcher.
This test feeds each hook deliberately malformed JSON and asserts the hook
exits cleanly (0 or 2 — 2 is acceptable for fail-CLOSED security guards).

A regression here means a hook would block every tool call on its matcher
when the input is unparseable. Fail this test in CI before that ships.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent

# Hooks that intentionally fail-CLOSED on crash (exit 2 acceptable).
FAIL_CLOSED = {
    "bash-security-guard.py",
    "config-guard.py",
    "memory-write-guard.py",
}

# Hooks that aren't standalone entrypoints (module-level code or libraries
# imported by other hooks) — not subjected to the stdin test.
NOT_ENTRYPOINTS = {
    "atomic_write.py",
    "hook_input.py",  # shared accessors imported by other hooks
    "manifest_metrics.py",
    "tavily-search-cap.py",  # module-level, no main()
    "stop-failure-handler.py",  # module-level, no main()
    "prompt-secret-scan.py",  # has its own crash test in test_prompt_secret_scan.py
    # nessus-to-md.py / pdf-to-text.py / cklb-to-md.py / xlsx-to-md.py
    # invoke subprocesses with their own behavior — covered by dedicated tests.
    "nessus-to-md.py",
    "pdf-to-text.py",
    "cklb-to-md.py",
    "xlsx-to-md.py",
    # write-edit-dispatcher dispatches to other guards; tested via the guards.
    "write-edit-dispatcher.py",
}


def all_hook_files():
    return sorted(p for p in HOOKS_DIR.glob("*.py") if p.is_file())


@pytest.mark.parametrize("hook_path", all_hook_files(), ids=lambda p: p.name)
def test_hook_does_not_crash_on_malformed_input(hook_path):
    """A malformed stdin must NOT cause the hook to exit with a traceback
    (rc=1) or signal kill — those block the tool call on the matcher."""
    if hook_path.name in NOT_ENTRYPOINTS:
        pytest.skip(f"{hook_path.name} is not a standalone hook entrypoint")
    # Send obviously-malformed JSON.
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input="this is not valid json {{{ broken",
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(HOOKS_DIR.parent),
    )
    expected_ok = {0, 2}  # 2 acceptable for fail-CLOSED guards
    assert result.returncode in expected_ok, (
        f"{hook_path.name} returned rc={result.returncode} on malformed input "
        f"(must be in {expected_ok}). stderr:\n{result.stderr}"
    )


@pytest.mark.parametrize("hook_path", all_hook_files(), ids=lambda p: p.name)
def test_hook_does_not_crash_on_empty_input(hook_path):
    if hook_path.name in NOT_ENTRYPOINTS:
        pytest.skip(f"{hook_path.name} is not a standalone hook entrypoint")
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input="",
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(HOOKS_DIR.parent),
    )
    expected_ok = {0, 2}
    assert result.returncode in expected_ok, (
        f"{hook_path.name} returned rc={result.returncode} on empty stdin "
        f"(must be in {expected_ok}). stderr:\n{result.stderr}"
    )


@pytest.mark.parametrize("hook_path", all_hook_files(), ids=lambda p: p.name)
def test_hook_does_not_crash_on_empty_object_input(hook_path):
    """A bare empty JSON object {} must not crash — Claude Code can send
    minimal hook input when fields aren't applicable."""
    if hook_path.name in NOT_ENTRYPOINTS:
        pytest.skip(f"{hook_path.name} is not a standalone hook entrypoint")
    result = subprocess.run(
        [sys.executable, str(hook_path)],
        input=json.dumps({}),
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(HOOKS_DIR.parent),
    )
    expected_ok = {0, 2}
    assert result.returncode in expected_ok, (
        f"{hook_path.name} returned rc={result.returncode} on {{}} input "
        f"(must be in {expected_ok}). stderr:\n{result.stderr}"
    )
