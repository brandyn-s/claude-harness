#!/usr/bin/env python3
"""PreToolUse guard: cap tavily_search max_results to 5.

Blocks calls with max_results > 5 and instructs Claude to retry with
max_results=5. Empirically verified savings: ~2.4M tokens/month
(1,486 calls * 6,405B avg reduction at 4 chars/token).
"""
import json
import sys

try:
    data = json.loads(sys.stdin.read())
except (json.JSONDecodeError, EOFError):
    sys.exit(0)

tool_name = data.get("tool_name", "")
if tool_name != "mcp__tavily__tavily_search":
    sys.exit(0)

tool_input = data.get("tool_input", {})
max_results = tool_input.get("max_results")

if max_results is None:
    sys.exit(0)

try:
    max_results = int(max_results)
except (ValueError, TypeError):
    sys.exit(0)

if max_results > 5:
    # Clamp instead of block. The cap's only purpose is token control, which a
    # silent rewrite achieves at zero friction — a hard block here cost +1
    # correction turn (the model had to re-issue the whole call). 2026-06-27
    # friction audit: 73 blocks/14d, every one trivially satisfiable by clamping.
    print(json.dumps({
        "decision": "approve",
        "reason": (
            f"[tavily-cap] clamped max_results {max_results} -> 5 "
            "(token control; ~1,200B saved per dropped result)."
        ),
        "updated_input": {**tool_input, "max_results": 5},
    }))
    sys.exit(0)

# Advisory: nudge about token-efficient parameters when not already set
chunks = tool_input.get("chunks_per_source")
depth = tool_input.get("search_depth", "basic")
if chunks is None and depth in ("basic", None):
    print(
        "[tavily-hint] TIP: Add search_depth='advanced' + chunks_per_source=3 "
        "for token-efficient results (500-char snippets vs full pages).",
        file=sys.stderr,
    )

sys.exit(0)
