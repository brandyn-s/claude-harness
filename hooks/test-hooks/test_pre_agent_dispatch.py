"""Tests for pre-agent-dispatch.py (PreToolUse:Agent)."""
import json

from conftest import run_hook

HOOK = "pre-agent-dispatch.py"


def test_no_auth_keywords_no_warning():
    rc, out, err = run_hook(HOOK, {"input": {"prompt": "Read the file and summarize it"}})
    assert rc == 0
    if out.strip():
        data = json.loads(out)
        assert "Auth warning" not in data.get("hookSpecificOutput", {}).get("additionalContext", "")


def test_crowdstrike_keyword_warns():
    rc, out, err = run_hook(HOOK, {
        "input": {"prompt": "Query crowdstrike for detections on host PROD-01"}
    })
    assert rc == 0
    if out.strip():
        data = json.loads(out)
        assert "Auth warning" in data.get("hookSpecificOutput", {}).get("additionalContext", "") or "crowdstrike" in data.get("hookSpecificOutput", {}).get("additionalContext", "").lower()


def test_multiple_auth_keywords():
    rc, out, err = run_hook(HOOK, {
        "input": {"prompt": "Use tenable and crowdstrike to correlate vulnerabilities"}
    })
    assert rc == 0
    if out.strip():
        data = json.loads(out)
        msg = data.get("hookSpecificOutput", {}).get("additionalContext", "").lower()
        assert "crowdstrike" in msg
        assert "tenable" in msg


def test_empty_prompt_no_crash():
    rc, out, err = run_hook(HOOK, {"input": {"prompt": ""}})
    assert rc == 0


def test_invalid_input_no_crash():
    rc, out, err = run_hook(HOOK, {})
    assert rc == 0


def test_canonical_tool_input_key_works():
    """Claude Code's canonical PreToolUse field is `tool_input`; legacy hooks
    that read `input` silently no-op'd. Regression guard."""
    rc, out, _ = run_hook(HOOK, {
        "tool_name": "Agent",
        "tool_input": {"prompt": "Query crowdstrike for detections on host PROD-01"},
    })
    assert rc == 0
    # The auth keyword should be detected via tool_input the same way as via input.
    assert out.strip(), "expected the keyword check to fire with the tool_input key"


# ── worktree-isolation guard: runtime-path masking (2026-08-16) ──────────

# Verbatim shape of the real blocked dispatch: reads gitignored transcripts
# under ~/.claude/projects/, writes its OUTPUT outside the repo. Not a
# claude-config write; must NOT block.
_TRANSCRIPT_MINING_PROMPT = (
    "Mine Claude Code session transcripts for a weekly status update. "
    "List files under ~/.claude/projects/ with find, then for the top 12 "
    "write your output to /tmp/claude/weekly-transcript-mine.md as two "
    "markdown tables."
)


def test_transcript_mining_prompt_not_blocked():
    """Kills the mutation that removes RUNTIME_NON_REPO_SUBPATHS masking:
    without the mask, '.claude' matches '~/.claude/projects/' and the
    'write...md' verbs satisfy WRITE_INDICATORS -> exit 2. With the mask,
    no protected-repo mention remains -> exit 0, no block decision."""
    rc, out, _ = run_hook(HOOK, {
        "tool_name": "Agent",
        "tool_input": {"prompt": _TRANSCRIPT_MINING_PROMPT},
    })
    assert rc == 0, f"transcript-mining dispatch was blocked: {out}"
    if out.strip():
        assert json.loads(out).get("decision") != "block"


def test_repo_content_write_still_blocked():
    """The mask must not weaken the real protection: a write targeting repo
    content under ~/.claude (skills/) without isolation still blocks."""
    rc, out, _ = run_hook(HOOK, {
        "tool_name": "Agent",
        "tool_input": {"prompt": (
            "Edit the SKILL.md file in ~/.claude/skills/weekly-update/ "
            "to add a new section about pagination."
        )},
    })
    assert rc == 2, "protected-repo write dispatch should still block"
    assert json.loads(out).get("decision") == "block"


def test_mixed_runtime_and_repo_mention_still_blocked():
    """Over-masking guard: a prompt that mentions BOTH a runtime path and
    repo content must still block — masking removes only the runtime
    substring, not the repo mention."""
    rc, out, _ = run_hook(HOOK, {
        "tool_name": "Agent",
        "tool_input": {"prompt": (
            "Read transcripts in ~/.claude/projects/ and then update the "
            "hook file in ~/.claude/hooks/pre-agent-dispatch.py accordingly."
        )},
    })
    assert rc == 2, "repo-content mention alongside runtime path should still block"
    assert json.loads(out).get("decision") == "block"
