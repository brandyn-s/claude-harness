"""Smoke tests for query-routing-log.py.

PostToolUse hook: logs codebase-memory-mcp (search/graph) and memory-search
calls to JSONL. Always exits 0 (non-blocking); writes
~/.claude/query-routing-log.jsonl.
"""
import json
import os
from pathlib import Path

from conftest import run_hook

HOOK = "query-routing-log.py"
LOG_PATH = Path.home() / ".claude" / "query-routing-log.jsonl"


def _last_log_entry():
    if not LOG_PATH.exists():
        return None
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return json.loads(lines[-1]) if lines else None


def _count_before():
    if not LOG_PATH.exists():
        return 0
    with open(LOG_PATH, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def test_untracked_tool_passes_through_without_logging():
    before = _count_before()
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "Bash",
        "tool_input": {"command": "ls"},
    })
    assert rc == 0
    assert json.loads(stdout) == {"allow": True}
    assert _count_before() == before  # no new log line


def test_code_search_logged_with_query_and_results():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__codebase-memory-mcp__search_code",
        "tool_input": {"query": "auth middleware"},
        "tool_result": json.dumps({"results": [1, 2, 3]}),
    })
    assert rc == 0
    assert json.loads(stdout) == {"allow": True}
    entry = _last_log_entry()
    assert entry["tool"] == "mcp__codebase-memory-mcp__search_code"
    assert entry["query"] == "auth middleware"
    assert entry["results"] == 3


def test_code_graph_total_nodes_count_captured():
    rc, _, _ = run_hook(HOOK, {
        "tool_name": "mcp__codebase-memory-mcp__query_graph",
        "tool_input": {"query": "FindCallers"},
        "tool_result": json.dumps({"total_nodes": 42}),
    })
    assert rc == 0
    entry = _last_log_entry()
    assert entry["tool"] == "mcp__codebase-memory-mcp__query_graph"
    assert entry["results"] == 42


def test_memory_search_captures_agreement_score():
    rc, _, _ = run_hook(HOOK, {
        "tool_name": "mcp__memory-search__memory_search",
        "tool_input": {"query": "feedback on ship"},
        "tool_result": json.dumps({
            "results": [1, 2],
            "metadata": {"agreement_score": 0.87, "latency_ms": 123.456},
        }),
    })
    assert rc == 0
    entry = _last_log_entry()
    assert entry["agreement"] == 0.87
    assert entry["latency_ms"] == 123.5


def test_malformed_tool_result_does_not_crash():
    rc, stdout, _ = run_hook(HOOK, {
        "tool_name": "mcp__codebase-memory-mcp__search_code",
        "tool_input": {"query": "x"},
        "tool_result": "not-json-at-all",
    })
    assert rc == 0
    entry = _last_log_entry()
    assert entry["query"] == "x"
    assert entry["results"] == 0  # fell through the try/except


def test_query_text_truncated_at_500_chars():
    long_query = "a" * 1000
    rc, _, _ = run_hook(HOOK, {
        "tool_name": "mcp__codebase-memory-mcp__search_code",
        "tool_input": {"query": long_query},
        "tool_result": "{}",
    })
    assert rc == 0
    entry = _last_log_entry()
    assert len(entry["query"]) == 500
