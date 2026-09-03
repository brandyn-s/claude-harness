"""Tests for tavily-search-cap.py (PreToolUse)."""
import json

from conftest import run_hook

HOOK = "tavily-search-cap.py"


def test_over_cap_clamped():
    """2026-06-27: max_results>5 is CLAMPED to 5 (permissionDecision allow + updatedInput), not
    blocked. The cap is token control; a clamp achieves it at zero friction
    (was 73 hard blocks/14d, each a +1 correction turn)."""
    rc, out, _err = run_hook(HOOK, {
        "tool_name": "mcp__tavily__tavily_search",
        "tool_input": {"max_results": 10, "query": "test"},
    })
    assert rc == 0, f"expected clamp (approve, exit 0), got rc={rc}"
    payload = json.loads(out)
    assert payload["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert payload["hookSpecificOutput"]["updatedInput"]["max_results"] == 5
    assert payload["hookSpecificOutput"]["updatedInput"]["query"] == "test"  # other params preserved


def test_at_cap_allowed():
    rc, out, err = run_hook(HOOK, {
        "tool_name": "mcp__tavily__tavily_search",
        "tool_input": {"max_results": 5, "query": "test"},
    })
    assert rc == 0


def test_no_max_results_allowed():
    rc, out, err = run_hook(HOOK, {
        "tool_name": "mcp__tavily__tavily_search",
        "tool_input": {"query": "test"},
    })
    assert rc == 0


def test_wrong_tool_ignored():
    rc, out, err = run_hook(HOOK, {
        "tool_name": "mcp__exa__web_search_exa",
        "tool_input": {"max_results": 20},
    })
    assert rc == 0


def test_boundary_six_clamped():
    rc, out, _err = run_hook(HOOK, {
        "tool_name": "mcp__tavily__tavily_search",
        "tool_input": {"max_results": 6, "query": "test"},
    })
    assert rc == 0
    assert json.loads(out)["hookSpecificOutput"]["updatedInput"]["max_results"] == 5


def test_hint_shown_when_no_chunks():
    """Advisory hint about chunks_per_source appears when not set."""
    rc, out, err = run_hook(HOOK, {
        "tool_name": "mcp__tavily__tavily_search",
        "tool_input": {"max_results": 5, "query": "test"},
    })
    assert rc == 0
    assert "chunks_per_source" in err


def test_hint_suppressed_when_chunks_set():
    """No hint when chunks_per_source is already specified."""
    rc, out, err = run_hook(HOOK, {
        "tool_name": "mcp__tavily__tavily_search",
        "tool_input": {"max_results": 5, "query": "test", "chunks_per_source": 3},
    })
    assert rc == 0
    assert "chunks_per_source" not in err


def test_hint_suppressed_when_advanced_depth():
    """No hint when search_depth is already advanced."""
    rc, out, err = run_hook(HOOK, {
        "tool_name": "mcp__tavily__tavily_search",
        "tool_input": {"max_results": 5, "query": "test", "search_depth": "advanced"},
    })
    assert rc == 0
    assert "chunks_per_source" not in err
