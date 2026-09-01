import json

from conftest import run_hook

HOOK = "mcp-output-trimmer.py"


def test_small_or_non_mcp_output_is_unchanged() -> None:
    for payload in (
        {"tool_name": "mcp__demo__list", "tool_response": "small"},
        {"tool_name": "Bash", "tool_response": "x" * 50000},
    ):
        rc, stdout, _ = run_hook(HOOK, payload)
        assert rc == 0
        assert stdout == ""


def test_large_plain_output_is_replaced_with_bounded_output() -> None:
    rc, stdout, _ = run_hook(
        HOOK,
        {"tool_name": "mcp__demo__list", "tool_response": "x" * 50000},
    )
    assert rc == 0
    payload = json.loads(stdout)
    trimmed = payload["hookSpecificOutput"]["updatedMCPToolOutput"]
    assert len(trimmed) < 50000
    assert "truncated" in trimmed


def test_large_json_remains_valid_json_after_trimming() -> None:
    response = json.dumps({"resources": [{"value": "x" * 2000} for _ in range(50)]})
    rc, stdout, _ = run_hook(
        HOOK,
        {"tool_name": "mcp__demo__list", "tool_response": response},
    )
    assert rc == 0
    payload = json.loads(stdout)
    trimmed = payload["hookSpecificOutput"]["updatedMCPToolOutput"]
    assert len(trimmed) <= 25000
    assert json.loads(trimmed)
