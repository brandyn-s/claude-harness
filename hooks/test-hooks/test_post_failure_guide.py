"""Tests for post-failure-guide.py (PostToolUseFailure)."""
import json
from conftest import run_hook

HOOK = "post-failure-guide.py"


def test_max_file_read_token_exceeded():
    rc, out, err = run_hook(HOOK, {
        "tool_name": "Read",
        "error": "MaxFileReadTokenExceeded: file too large",
    })
    assert rc == 0
    data = json.loads(out)
    assert "offset/limit" in data["message"] or "paginate" in data["message"]


def test_timeout_suggests_connectivity():
    rc, out, err = run_hook(HOOK, {
        "tool_name": "mcp__remote-tenable__list_vulns",
        "error": "Request timeout after 30s",
    })
    assert rc == 0
    data = json.loads(out)
    assert "timeout" in data["message"].lower() or "connectivity" in data["message"].lower()


def test_unknown_tool_suggests_toolsearch():
    rc, out, err = run_hook(HOOK, {
        "tool_name": "mcp__foo__bar",
        "error": "Unknown tool: mcp__foo__bar",
    })
    assert rc == 0
    data = json.loads(out)
    assert "ToolSearch" in data["message"]


def test_no_error_still_produces_message():
    rc, out, err = run_hook(HOOK, {
        "tool_name": "Bash",
        "error": "something unrecognized happened",
    })
    assert rc == 0
    data = json.loads(out)
    assert "Diagnose root cause" in data["message"]
