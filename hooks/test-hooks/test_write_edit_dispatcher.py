"""Behavior tests for write-edit-dispatcher.py.

Contract: PreToolUse:Write|Edit. Runs four sub-guards (memory-write,
config, worktree-enforcement, rule-size) in one process; first guard to
return exit 2 short-circuits the dispatcher to exit 2. Benign edits and
malformed/empty input pass (exit 0).

Fail posture (B2/F4): an "open" guard's crash must never block; the
"closed" guard (config-guard) blocks when it is missing or crashes,
unless SKIP_CONFIG_GUARD is set (deliberate bypass).
"""
import json
import os
import shutil
import subprocess
from conftest import run_hook, make_write_input, HOOKS_DIR, PYTHON

HOOK = "write-edit-dispatcher.py"


def _run_raw(stdin_text):
    r = subprocess.run([PYTHON, str(HOOKS_DIR / HOOK)], input=stdin_text,
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=15, cwd=str(HOOKS_DIR.parent))
    return r.returncode, r.stdout, r.stderr


def _make_sandbox_dispatcher(tmp_path, broken=(), missing=()):
    """Copy the dispatcher into a tmp hooks dir where the named guards are
    replaced with a crashing check() (`broken`) or absent (`missing`);
    every other guard becomes a benign allow-all stub. Lets the posture
    paths run end-to-end without touching the real guards."""
    guard_files = ["memory-write-guard.py", "config-guard.py",
                   "worktree-enforcement.py", "rule-size-guard.py"]
    shutil.copy2(HOOKS_DIR / HOOK, tmp_path / HOOK)
    for fname in guard_files:
        if fname in missing:
            continue
        if fname in broken:
            (tmp_path / fname).write_text(
                "def check(hook_input):\n    raise RuntimeError('boom')\n",
                encoding="utf-8")
        else:
            (tmp_path / fname).write_text(
                "def check(hook_input):\n    return (0, '', '')\n",
                encoding="utf-8")
    return tmp_path / HOOK


def _run_sandbox(dispatcher_path, extra_env=None):
    env = {k: v for k, v in os.environ.items() if k != "SKIP_CONFIG_GUARD"}
    if extra_env:
        env.update(extra_env)
    stdin = json.dumps({"tool_name": "Write", "tool_input": {
        "file_path": "/tmp/x.txt", "content": "hi"}})
    r = subprocess.run([PYTHON, str(dispatcher_path)], input=stdin,
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=15, env=env)
    return r.returncode, r.stdout, r.stderr


def test_closed_guard_crash_blocks(tmp_path):
    d = _make_sandbox_dispatcher(tmp_path, broken=("config-guard.py",))
    code, _o, err = _run_sandbox(d)
    assert code == 2
    assert "fail-closed guard 'config-guard'" in err


def test_closed_guard_missing_blocks(tmp_path):
    d = _make_sandbox_dispatcher(tmp_path, missing=("config-guard.py",))
    code, _o, err = _run_sandbox(d)
    assert code == 2
    assert "missing or failed to load" in err


def test_closed_guard_crash_bypassed_with_skip_env(tmp_path):
    d = _make_sandbox_dispatcher(tmp_path, broken=("config-guard.py",))
    code, _o, err = _run_sandbox(d, extra_env={"SKIP_CONFIG_GUARD": "1"})
    assert code == 0
    assert "SKIP_CONFIG_GUARD" in err


def test_open_guard_crash_does_not_block(tmp_path):
    d = _make_sandbox_dispatcher(tmp_path, broken=("memory-write-guard.py",))
    code, _o, err = _run_sandbox(d)
    assert code == 0
    assert "memory-write-guard" in err  # loud, not silent


def test_benign_write_passes():
    code, _o, _e = run_hook(HOOK, make_write_input("/tmp/__audit_dispatch__.txt", "hello world"))
    assert code == 0


def test_oversize_rules_write_blocks_via_rule_size_guard():
    # Exercises the dispatcher -> rule-size-guard path end to end.
    code, _o, err = run_hook(
        HOOK, make_write_input("~/.claude/rules/__audit_dispatch__.md", "x" * 39000))
    assert code == 2
    assert "rule-size-guard" in err


def test_empty_stdin_passes():
    code, _o, _e = _run_raw("")
    assert code == 0


def test_malformed_json_passes():
    code, _o, _e = _run_raw("{not valid json")
    assert code == 0
