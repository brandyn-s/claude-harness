"""Tests for tavily-research-poll.py (PostToolUse)."""
import json
from conftest import run_hook

HOOK = "tavily-research-poll.py"


def test_timeout_with_request_id_injects_poll():
    inner = json.dumps({
        "status": "timeout",
        "request_id": "req-abc",
        "elapsed_seconds": 45,
        "model": "gpt-4",
    })
    rc, out, err = run_hook(HOOK, {
        "tool_result": {"result": inner},
    })
    assert rc == 0
    assert out.strip(), "expected poll instructions for the model"
    data = json.loads(out)
    assert data["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "req-abc" in data["hookSpecificOutput"]["additionalContext"]


def test_completed_status_no_output():
    inner = json.dumps({
        "status": "completed",
        "request_id": "req-abc",
    })
    rc, out, err = run_hook(HOOK, {
        "tool_result": {"result": inner},
    })
    assert rc == 0
    assert out.strip() == ""


def test_timeout_without_request_id_no_output():
    inner = json.dumps({"status": "timeout"})
    rc, out, err = run_hook(HOOK, {
        "tool_result": {"result": inner},
    })
    assert rc == 0
    assert out.strip() == ""
