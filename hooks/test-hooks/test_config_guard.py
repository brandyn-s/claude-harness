"""Tests for config-guard.py hook self-protection."""
import importlib.util
import json
import os
import subprocess
import sys

# Load the module
_hook_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "config_guard", os.path.join(_hook_dir, "config-guard.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
PROTECTED_HOOKS = _mod.PROTECTED_HOOKS
SETTINGS_FILENAMES = _mod.SETTINGS_FILENAMES


def test_protected_hooks_list():
    """All critical hooks are in the protected list."""
    assert "bash-security-guard.py" in PROTECTED_HOOKS
    assert "config-guard.py" in PROTECTED_HOOKS  # self-protection
    print("PASS: protected hooks list complete")


def test_settings_filenames():
    """Both settings files are monitored."""
    assert "settings.json" in SETTINGS_FILENAMES
    assert "settings.local.json" in SETTINGS_FILENAMES
    print("PASS: settings filenames covered")


def test_detects_disable_all():
    """disableAllHooks=true in a settings Write blocks (exercise check(), not a
    re-implementation of its logic -- the old test asserted its own substring
    search, so the vacuous `"true" in content` check could never fail it)."""
    os.environ.pop("SKIP_CONFIG_GUARD", None)
    code, msg, _ = _mod.check({
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/home/user/.claude/settings.json",
            "content": '{"disableAllHooks": true, "hooks": {"PreToolUse": []}}',
        },
    })
    assert code == 2 and "disableAllHooks" in msg
    print("PASS: detects disableAllHooks=true")


def test_allows_normal_edits():
    """Normal settings edits should not trigger."""
    code, msg, _ = _mod.check({
        "tool_name": "Write",
        "tool_input": {
            "file_path": "/home/user/.claude/settings.json",
            "content": '{"permissions": {"allow": ["Read(**)"]}}',
        },
    })
    assert code == 0, msg
    print("PASS: allows normal settings edits")


def test_disable_all_hooks_false_beside_other_true_values_is_allowed(monkeypatch):
    """Review 2026-09-03: the check was `"disableAllHooks" in content and "true"
    in content.lower()`, so `"disableAllHooks": false` was blocked whenever ANY
    other key in the same write was true (`"enabled": true` is in nearly every
    settings.json). Match the key/value pair, not two independent substrings."""
    monkeypatch.delenv("SKIP_CONFIG_GUARD", raising=False)
    code, msg, _ = _mod.check({
        "tool_name": "Write",
        "tool_input": {
            "file_path": "settings.json",
            "content": '{"disableAllHooks": false, "sandbox": {"enabled": true}, '
                       '"hooks": {"PreToolUse": []}}',
        },
    })
    assert code == 0, msg


def test_crash_inside_check_fails_closed():
    """Wired directly (the fresh-laptop profile) there is no dispatcher wrapper,
    so an exception inside check() must exit 2. Exit 1 is a NON-blocking error
    in Claude Code, which would make a crashed self-protection guard fail open."""
    hook = os.path.join(_hook_dir, "config-guard.py")
    proc = subprocess.run(
        [sys.executable, hook],
        input=json.dumps({"tool_name": "Write", "tool_input": "not-a-dict"}),
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 2, (proc.returncode, proc.stderr)
    assert "config-guard" in proc.stderr


def test_detects_hook_deletion_command():
    """rm command targeting a protected hook should be detected."""
    for hook in ["bash-security-guard.py", "config-guard.py"]:
        cmd = f"rm ~/.claude/hooks/{hook}"
        assert hook in cmd and "rm " in cmd
    print("PASS: detects hook deletion in commands")


def test_multiedit_disable_all_hooks_blocked():
    """A MultiEdit disabling hooks must be blocked just like Write/Edit — the
    payload lives under edits[].new_string, which the guard previously ignored."""
    hook_input = {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": "/home/user/.claude/settings.json",
            "edits": [{"old_string": "x", "new_string": '"disableAllHooks": true'}],
        },
    }
    code, _, _ = _mod.check(hook_input)
    assert code == 2


def test_multiedit_empty_hooks_blocked():
    hook_input = {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": "/home/user/.claude/settings.json",
            "edits": [{"old_string": "x", "new_string": '"hooks": {}'}],
        },
    }
    code, _, _ = _mod.check(hook_input)
    assert code == 2


def test_edit_empty_hooks_blocked():
    """Empty-hooks `{}` via an Edit fragment (not a full Write) is blocked."""
    hook_input = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/home/user/.claude/settings.json",
            "new_string": 'something "hooks": {} else',
        },
    }
    code, _, _ = _mod.check(hook_input)
    assert code == 2


def test_multiedit_normal_settings_allowed():
    hook_input = {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": "/home/user/.claude/settings.json",
            "edits": [{"old_string": "x", "new_string": '"theme": "dark"'}],
        },
    }
    code, _, _ = _mod.check(hook_input)
    assert code == 0


if __name__ == "__main__":
    test_protected_hooks_list()
    test_settings_filenames()
    test_detects_disable_all()
    test_allows_normal_edits()
    test_detects_hook_deletion_command()
    test_multiedit_disable_all_hooks_blocked()
    test_multiedit_empty_hooks_blocked()
    test_edit_empty_hooks_blocked()
    test_multiedit_normal_settings_allowed()
    print("All config-guard tests passed.")


def test_skip_config_guard_env_honored(monkeypatch):
    """B2 regression: the disableAllHooks block message advertises
    SKIP_CONFIG_GUARD=1 as the escape hatch; the guard must actually read it."""
    monkeypatch.setenv("SKIP_CONFIG_GUARD", "1")
    code, _, _ = _mod.check({
        "tool_name": "Write",
        "tool_input": {"file_path": "settings.json", "content": '{"disableAllHooks": true}'},
    })
    assert code == 0


def test_disable_all_hooks_blocked_without_skip(monkeypatch):
    monkeypatch.delenv("SKIP_CONFIG_GUARD", raising=False)
    code, msg, _ = _mod.check({
        "tool_name": "Write",
        "tool_input": {"file_path": "settings.json", "content": '{"disableAllHooks": true}'},
    })
    assert code == 2
    assert "disableAllHooks" in msg
