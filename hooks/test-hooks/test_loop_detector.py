"""Tests for loop-detector.py (ASI08).

Validates no-op loop and retry storm detection via session-scoped ring buffer.
"""
import json
import subprocess
from pathlib import Path

from conftest import HOOKS_DIR, PYTHON, run_hook

HOOK = "loop-detector.py"
SESSION_ENV = Path.home() / ".claude" / "session-env"
TEST_SESSION = "test-loop-detect"


def make_posttool_input(tool_name, tool_input=None, is_error=False):
    return {
        "tool_name": tool_name,
        "tool_input": tool_input or {},
        "is_error": is_error,
        "session_id": TEST_SESSION,
    }


def cleanup_history():
    f = SESSION_ENV / f"tool-history-{TEST_SESSION}.json"
    if f.exists():
        f.unlink()


def setup_function():
    cleanup_history()


def teardown_function():
    cleanup_history()


# ── No-op loop detection ──


def test_single_call_no_warning():
    rc, stdout, _ = run_hook(HOOK, make_posttool_input("Bash", {"command": "ls"}))
    assert rc == 0
    assert not stdout.strip() or "LOOP" not in stdout


def test_two_identical_calls_no_warning():
    inp = make_posttool_input("Grep", {"pattern": "foo", "path": "/tmp"})
    run_hook(HOOK, inp)
    rc, stdout, _ = run_hook(HOOK, inp)
    assert rc == 0
    assert not stdout.strip() or "LOOP" not in stdout


def test_three_identical_calls_triggers_loop():
    inp = make_posttool_input("Grep", {"pattern": "foo", "path": "/tmp"})
    run_hook(HOOK, inp)
    run_hook(HOOK, inp)
    rc, stdout, _ = run_hook(HOOK, inp)
    assert rc == 0
    out = json.loads(stdout)
    assert "LOOP DETECTED" in out.get("hookSpecificOutput", {}).get("additionalContext", "")


def test_no_loop_with_different_inputs():
    run_hook(HOOK, make_posttool_input("Bash", {"command": "ls"}))
    run_hook(HOOK, make_posttool_input("Bash", {"command": "pwd"}))
    rc, stdout, _ = run_hook(HOOK, make_posttool_input("Bash", {"command": "date"}))
    assert rc == 0
    assert not stdout.strip() or "LOOP" not in stdout


def test_no_loop_with_different_tools():
    run_hook(HOOK, make_posttool_input("Bash", {"command": "ls"}))
    run_hook(HOOK, make_posttool_input("Read", {"file_path": "/tmp/x"}))
    rc, stdout, _ = run_hook(HOOK, make_posttool_input("Grep", {"pattern": "x"}))
    assert rc == 0
    assert not stdout.strip() or "LOOP" not in stdout


# ── Retry storm detection ──


def test_four_failures_triggers_storm():
    inp = make_posttool_input(
        "mcp__tavily__tavily_search", {"query": "test"}, is_error=True
    )
    run_hook(HOOK, inp)
    run_hook(HOOK, inp)
    run_hook(HOOK, inp)
    rc, stdout, _ = run_hook(HOOK, inp)
    assert rc == 0
    out = json.loads(stdout)
    assert "RETRY STORM" in out.get("hookSpecificOutput", {}).get("additionalContext", "")


def test_three_failures_no_storm():
    inp = make_posttool_input("Bash", {"command": "bad"}, is_error=True)
    run_hook(HOOK, inp)
    run_hook(HOOK, inp)
    rc, stdout, _ = run_hook(HOOK, inp)
    assert rc == 0
    assert not stdout.strip() or "RETRY STORM" not in stdout


def test_success_between_failures_resets_storm():
    fail = make_posttool_input("Bash", {"command": "bad"}, is_error=True)
    ok = make_posttool_input("Bash", {"command": "good"}, is_error=False)
    run_hook(HOOK, fail)
    run_hook(HOOK, fail)
    run_hook(HOOK, ok)  # breaks the streak
    rc, stdout, _ = run_hook(HOOK, fail)
    assert rc == 0
    assert not stdout.strip() or "RETRY STORM" not in stdout


# ── Edge cases ──


def test_invalid_json_exits_clean():
    result = subprocess.run(
        [PYTHON, str(HOOKS_DIR / HOOK)],
        input="not json",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    assert result.returncode == 0
