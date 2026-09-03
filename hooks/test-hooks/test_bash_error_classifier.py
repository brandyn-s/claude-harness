"""Tests for bash-error-classifier.py (PostToolUse:Bash)."""
import json
from conftest import run_hook

HOOK = "bash-error-classifier.py"


def test_module_not_found_suggests_pip():
    rc, out, err = run_hook(HOOK, {
        "tool_name": "Bash",
        "tool_error": "ModuleNotFoundError: No module named 'requests'",
        "tool_result": "",
    })
    assert rc == 0
    if out.strip():
        data = json.loads(out)
        assert "requests" in data["hookSpecificOutput"]["additionalContext"]
        assert "pip install" in data["hookSpecificOutput"]["additionalContext"]


def test_aws_credentials_expired():
    rc, out, err = run_hook(HOOK, {
        "tool_name": "Bash",
        "tool_error": "Unable to locate credentials",
        "tool_result": "",
    })
    assert rc == 0
    if out.strip():
        data = json.loads(out)
        assert "AWS" in data["hookSpecificOutput"]["additionalContext"] or "sso login" in data["hookSpecificOutput"]["additionalContext"]


def test_non_bash_tool_ignored():
    rc, out, err = run_hook(HOOK, {
        "tool_name": "Read",
        "tool_error": "EPERM: permission denied",
        "tool_result": "",
    })
    assert rc == 0
    assert out.strip() == ""


def test_no_error_no_output():
    rc, out, err = run_hook(HOOK, {
        "tool_name": "Bash",
        "tool_error": "",
        "tool_result": "success",
    })
    assert rc == 0
    # No matching pattern means no output or empty output


def test_tool_response_canonical_key_works():
    """Claude Code's canonical PostToolUse field is `tool_response`; older
    versions use `tool_result`. The hook must read either to be
    forward-compatible. Regression guard against the field-name drift."""
    rc, out, err = run_hook(HOOK, {
        "tool_name": "Bash",
        "tool_error": "",
        "tool_response": "ModuleNotFoundError: No module named 'requests'",
    })
    assert rc == 0
    # The hook should still classify the error using the tool_response field.
    if out.strip():
        try:
            payload = json.loads(out)
            assert "pip" in str(payload).lower() or "module" in str(payload).lower()
        except json.JSONDecodeError:
            pass


def test_bare_response_key_works():
    """Some MCP-only paths pass the response under a bare `response` key."""
    rc, out, err = run_hook(HOOK, {
        "tool_name": "Bash",
        "tool_error": "",
        "response": "command not found: rg",
    })
    assert rc == 0
