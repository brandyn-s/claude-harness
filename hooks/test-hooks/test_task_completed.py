"""Tests for task-completed.py (TaskCompleted).

Covers the Phase D enforcement gate:
- PASS: completed task with no explicit failure signal -> exit 0
- BLOCK: explicit structured failure signal -> exit 2 with actionable reason
- FAIL-OPEN: malformed input must never block -> exit 0
"""
import json
import os
from conftest import run_hook

HOOK = "task-completed.py"


# ── PASS cases (no explicit failure signal -> exit 0) ───────────────────

def test_in_git_repo():
    """Running in a git repo should always exit 0 (no failure signal)."""
    rc, out, err = run_hook(HOOK, {"cwd": os.path.expanduser("~/.claude")})
    assert rc == 0
    data = json.loads(out)
    assert data["result"] == "pass"
    assert "TaskCompleted" in data["message"]


def test_in_non_git_dir():
    """Non-git directory should not crash."""
    import tempfile
    tmp = tempfile.mkdtemp()
    rc, out, err = run_hook(HOOK, {"cwd": tmp})
    assert rc == 0
    data = json.loads(out)
    assert data["result"] == "pass"
    os.rmdir(tmp)


def test_explicit_success_passes():
    """A payload that explicitly reports success must pass (exit 0)."""
    rc, out, err = run_hook(
        HOOK,
        {"cwd": os.path.expanduser("~/.claude"), "status": "completed", "success": True},
    )
    assert rc == 0
    data = json.loads(out)
    assert data["result"] == "pass"


def test_status_completed_with_errors_does_not_block():
    """Conservative: only EXACT failure statuses block. 'completed_with_errors'
    is not an exact failure token, so it must NOT spuriously block."""
    rc, out, err = run_hook(
        HOOK,
        {"cwd": os.path.expanduser("~/.claude"), "status": "completed_with_errors"},
    )
    assert rc == 0


def test_prose_mentioning_error_does_not_block():
    """Free text mentioning 'error' is never sniffed -- must pass."""
    rc, out, err = run_hook(
        HOOK,
        {
            "cwd": os.path.expanduser("~/.claude"),
            "result": {"summary": "Investigated the error and documented it."},
        },
    )
    assert rc == 0


# ── BLOCK cases (explicit failure signal -> exit 2) ─────────────────────

def test_explicit_failure_status_blocks():
    """A top-level status of 'failed' is an explicit failure -> block."""
    rc, out, err = run_hook(
        HOOK,
        {"cwd": os.path.expanduser("~/.claude"), "status": "failed"},
    )
    assert rc == 2
    assert "BLOCK" in err
    assert "failed" in err


def test_success_false_blocks():
    """Explicit success=False is a failure signal -> block."""
    rc, out, err = run_hook(
        HOOK,
        {"cwd": os.path.expanduser("~/.claude"), "success": False},
    )
    assert rc == 2
    assert "BLOCK" in err


def test_nested_is_error_blocks():
    """is_error=true in the nested result body -> block."""
    rc, out, err = run_hook(
        HOOK,
        {
            "cwd": os.path.expanduser("~/.claude"),
            "result": {"is_error": True, "status": "error"},
        },
    )
    assert rc == 2
    assert "BLOCK" in err


# ── FAIL-OPEN cases (malformed input must never block) ──────────────────

def test_malformed_input_fails_open():
    """Garbage (non-JSON) on stdin must fail open: exit 0, never block."""
    from conftest import HOOKS_DIR, PYTHON
    import subprocess
    result = subprocess.run(
        [PYTHON, str(HOOKS_DIR / HOOK)],
        input="this is not json {{{",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        cwd=str(HOOKS_DIR.parent),
    )
    assert result.returncode == 0


def test_non_dict_json_fails_open():
    """A JSON value that isn't an object (e.g. a list) must not block."""
    from conftest import HOOKS_DIR, PYTHON
    import subprocess
    result = subprocess.run(
        [PYTHON, str(HOOKS_DIR / HOOK)],
        input=json.dumps(["failed", "error"]),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        cwd=str(HOOKS_DIR.parent),
    )
    assert result.returncode == 0


def test_empty_input_fails_open():
    """Empty stdin must pass (exit 0)."""
    from conftest import HOOKS_DIR, PYTHON
    import subprocess
    result = subprocess.run(
        [PYTHON, str(HOOKS_DIR / HOOK)],
        input="",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        cwd=str(HOOKS_DIR.parent),
    )
    assert result.returncode == 0
