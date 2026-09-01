import json

from conftest import run_hook

HOOK = "verify-before-assuming.py"


def test_unverified_unavailable_claim_emits_advisory(tmp_path) -> None:
    rc, stdout, _ = run_hook(
        HOOK,
        {
            "tool_name": "Agent",
            "tool_input": {"prompt": "The requested MCP server is unavailable, so skip this step."},
        },
        env={"HOME": str(tmp_path), "CLAUDE_SESSION_ID": "unverified-case"},
    )
    assert rc == 0
    assert "Verify-before-assuming" in json.loads(stdout)["systemMessage"]


def test_claim_with_cited_verification_does_not_warn(tmp_path) -> None:
    rc, stdout, _ = run_hook(
        HOOK,
        {
            "tool_name": "Agent",
            "tool_input": {
                "prompt": "I checked ToolSearch and confirmed the MCP server is unavailable."
            },
        },
        env={"HOME": str(tmp_path), "CLAUDE_SESSION_ID": "verified-case"},
    )
    assert rc == 0
    assert stdout == ""


def test_prior_toolsearch_suppresses_later_advisory(tmp_path) -> None:
    env = {"HOME": str(tmp_path), "CLAUDE_SESSION_ID": "same-session"}
    rc, stdout, _ = run_hook(HOOK, {"tool_name": "ToolSearch", "tool_input": {}}, env=env)
    assert rc == 0 and stdout == ""
    rc, stdout, _ = run_hook(
        HOOK,
        {
            "tool_name": "Skill",
            "tool_input": {"args": "Skip because the required server is unavailable."},
        },
        env=env,
    )
    assert rc == 0
    assert stdout == ""
