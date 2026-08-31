"""Behavior tests for bin/compliance-sample.py (DECIDE item 3).

Synthetic transcript fixtures pin the predicate semantics: git-hygiene
(push without PR evidence), bulk-data (limit>=100 routed/unrouted),
web-search-pref counts, and skill gate compliance (AskUserQuestion after
a gated-skill invocation; sidechains excluded by default).
"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "bin" / "compliance-sample.py"


def _event(tool_name=None, tool_input=None, user_text=None, sidechain=False):
    content = []
    if tool_name:
        content.append({"type": "tool_use", "name": tool_name,
                        "input": tool_input or {}})
        msg_type = "assistant"
    else:
        content.append({"type": "text", "text": user_text or ""})
        msg_type = "user"
    return json.dumps({
        "type": msg_type,
        "isSidechain": sidechain,
        "message": {"role": msg_type, "content": content},
    })


def _write_transcript(tmp_path, name, lines):
    proj = tmp_path / "-home-user"
    proj.mkdir(exist_ok=True)
    (proj / f"{name}.jsonl").write_text("\n".join(lines) + "\n",
                                        encoding="utf-8")


def _run(tmp_path, *extra):
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--transcripts-dir", str(tmp_path),
         "--json", *extra],
        capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_push_without_pr_counts_as_uncovered(tmp_path):
    _write_transcript(tmp_path, "s1", [
        _event("Bash", {"command": "git push -u origin feature"}),
    ])
    agg = _run(tmp_path)
    assert agg["git_hygiene"]["push_sessions"] == 1
    assert agg["git_hygiene"]["push_sessions_with_pr"] == 0


def test_push_with_mcp_pr_creation_is_covered(tmp_path):
    _write_transcript(tmp_path, "s1", [
        _event("Bash", {"command": "git push -u origin feature"}),
        _event("mcp__github__create_pull_request", {"title": "x"}),
    ])
    agg = _run(tmp_path)
    assert agg["git_hygiene"]["push_sessions_with_pr"] == 1


def test_bulk_call_routed_vs_unrouted(tmp_path):
    _write_transcript(tmp_path, "s1", [
        _event("mcp__Ramp__load_users", {"limit": 500}),
        _event("Bash", {"command": "python3 bulk_export.py"}),
        _event("mcp__Ramp__load_vendors", {"limit": 500}),
        # nothing after the second bulk call -> unrouted
    ])
    agg = _run(tmp_path)
    assert agg["bulk_data"]["bulk_calls"] == 2
    assert agg["bulk_data"]["bulk_routed_to_script"] == 1


def test_small_limit_is_not_bulk(tmp_path):
    _write_transcript(tmp_path, "s1", [
        _event("mcp__Linear__list_issues", {"limit": 25}),
    ])
    agg = _run(tmp_path)
    assert agg["bulk_data"]["bulk_calls"] == 0


def test_websearch_vs_mcp_search_counts(tmp_path):
    _write_transcript(tmp_path, "s1", [
        _event("WebSearch", {"query": "x"}),
        _event("mcp__tavily__tavily_search", {"query": "x"}),
        _event("mcp__exa__web_search_exa", {"query": "x"}),
    ])
    agg = _run(tmp_path)
    assert agg["web_search_pref"]["websearch_calls"] == 1
    assert agg["web_search_pref"]["mcp_search_calls"] == 2


def test_gated_skill_with_ask_user_fires(tmp_path):
    # ship's manifest carries AskUserQuestion (gate-bearing) — if that
    # ever changes, swap in another gated skill; the assertion message
    # names the dependency.
    _write_transcript(tmp_path, "s1", [
        _event("Skill", {"skill": "ship"}),
        _event("AskUserQuestion", {"questions": []}),
    ])
    agg = _run(tmp_path)
    gates = agg["skill_gates"]
    assert "ship" in gates, (
        "ship not treated as gate-bearing — check its manifest still "
        "lists AskUserQuestion in requires_tools")
    assert gates["ship"]["gate_fired"] == 1


def test_gated_skill_without_ask_user_is_flagged(tmp_path):
    _write_transcript(tmp_path, "s1", [
        _event("Skill", {"skill": "ship"}),
        _event("Bash", {"command": "echo done"}),
    ])
    agg = _run(tmp_path)
    assert agg["skill_gates"]["ship"]["gate_fired"] == 0


def test_command_marker_counts_as_invocation(tmp_path):
    _write_transcript(tmp_path, "s1", [
        _event(user_text="<command-name>/ship</command-name> args"),
    ])
    agg = _run(tmp_path)
    assert agg["skill_invocations"].get("ship") == 1


def test_sidechain_excluded_by_default(tmp_path):
    _write_transcript(tmp_path, "s1", [
        _event("WebSearch", {"query": "x"}, sidechain=True),
    ])
    agg = _run(tmp_path)
    assert agg["web_search_pref"]["websearch_calls"] == 0
    agg2 = _run(tmp_path, "--include-sidechains")
    assert agg2["web_search_pref"]["websearch_calls"] == 1


def test_garbage_lines_tolerated(tmp_path):
    _write_transcript(tmp_path, "s1", [
        "not json at all",
        json.dumps({"type": "summary", "compactMetadata": {}}),
        _event("Bash", {"command": "git push origin x"}),
    ])
    agg = _run(tmp_path)
    assert agg["sessions"] == 1
    assert agg["git_hygiene"]["push_sessions"] == 1


def test_missing_dir_exits_2(tmp_path):
    r = subprocess.run(
        [sys.executable, str(SCRIPT), "--transcripts-dir",
         str(tmp_path / "nope")],
        capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert r.returncode == 2
