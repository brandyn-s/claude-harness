#!/bin/sh
# Installed by: codebase-memory-mcp install
# Purpose: surface ARCHITECTURE_REPORT.md when the agent is about to grep/glob
# on a repo the code-graph MCP has already indexed.
# codebase-memory-orientation hook

project_dir="${CLAUDE_PROJECT_DIR:-$PWD}"
report="$project_dir/ARCHITECTURE_REPORT.md"

if [ -f "$report" ]; then
  echo "[code-graph] This repo has an indexed ARCHITECTURE_REPORT.md at $report." >&2
  echo "[code-graph] It lists god nodes, cohesive communities, cross-package boundaries, and 5 suggested graph queries." >&2
  echo "[code-graph] Prefer query_graph / trace_call_path / get_relevant_context over raw file search for structural questions." >&2
fi

exit 0
