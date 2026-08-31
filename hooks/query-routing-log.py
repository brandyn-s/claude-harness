"""PostToolUse hook: logs codebase-memory-mcp (search/graph) and memory-search
tool calls for query routing analysis.

Captures: tool name, query text, result count, latency, timestamp, and the
agreement_score (for memory-search) to a JSONL file.

Output: ~/.claude/query-routing-log.jsonl
"""

import json
import os
import sys
import time

TRACKED_PREFIXES = (
    "mcp__codebase-memory-mcp__search_code",
    "mcp__codebase-memory-mcp__search_code_semantic",
    "mcp__codebase-memory-mcp__query_graph",
    "mcp__codebase-memory-mcp__search_graph",
    "mcp__memory-search__memory_search",
)

QUERY_ARG_NAMES = ("query", "name", "source", "function_name", "name_pattern")


def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError, ValueError):
        # Malformed input must NOT block tool calls — fail open silently.
        sys.exit(0)
    tool_name = hook_input.get("tool_name", "")

    if not any(tool_name.startswith(p) for p in TRACKED_PREFIXES):
        # Pass-through marker. PostToolUse cannot block (the call already
        # happened); the {"allow": true} payload is kept only because
        # downstream tests and audit tooling expect it as a presence
        # marker. New PostToolUse hooks should NOT copy this pattern —
        # silent exit-0 is the canonical no-op.
        print(json.dumps({"allow": True}))
        sys.exit(0)

    tool_input = hook_input.get("tool_input", {})
    # PostToolUse field name varies across Claude Code versions; read all.
    tool_result = (
        hook_input.get("tool_response")
        or hook_input.get("tool_result")
        or hook_input.get("response")
        or ""
    )

    query_text = ""
    for arg_name in QUERY_ARG_NAMES:
        if arg_name in tool_input:
            query_text = str(tool_input[arg_name])
            break

    result_count = 0
    agreement_score = None
    latency_ms = None
    try:
        if isinstance(tool_result, str):
            parsed = json.loads(tool_result)
        elif isinstance(tool_result, dict):
            parsed = tool_result
        else:
            parsed = {}

        if "results" in parsed:
            result_count = len(parsed["results"])
        if "metadata" in parsed:
            meta = parsed["metadata"]
            agreement_score = meta.get("agreement_score")
            latency_ms = meta.get("latency_ms")
        if "result_count" in parsed:
            result_count = parsed["result_count"]
        if "total_nodes" in parsed:
            result_count = parsed["total_nodes"]
        if isinstance(parsed, list):
            result_count = len(parsed)
    except (json.JSONDecodeError, TypeError, AttributeError):
        pass

    entry = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "tool": tool_name,
        "query": query_text[:500],
        "results": result_count,
        "scope": tool_input.get("scope", ""),
        "project": tool_input.get("project", ""),
    }
    if agreement_score is not None:
        entry["agreement"] = agreement_score
    if latency_ms is not None:
        entry["latency_ms"] = round(latency_ms, 1)

    # Ground truth signal: detect follow-up queries to the same tool within 60s.
    # A follow-up suggests the first result was insufficient (negative signal).
    log_path = os.path.join(os.path.expanduser("~"), ".claude", "query-routing-log.jsonl")
    try:
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            if lines:
                last = json.loads(lines[-1])
                time_delta = entry["ts"] - last.get("ts", 0)
                same_tool = last.get("tool", "") == entry["tool"]
                if same_tool and 0 < time_delta < 60:
                    entry["follow_up"] = True
                    entry["prior_query"] = last.get("query", "")[:200]
                    entry["time_since_last"] = round(time_delta, 1)
    except (json.JSONDecodeError, OSError, KeyError):
        pass

    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass

    # Successful logging path: emit the same marker so downstream tooling
    # (audit / tests) sees consistent output. Exit code 0 is what matters
    # to Claude Code itself.
    print(json.dumps({"allow": True}))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # Last-resort fail-open. A logging hook must never block tools.
        sys.exit(0)
