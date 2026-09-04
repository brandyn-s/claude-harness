"""PostToolUseFailure hook: non-blocking diagnostic guidance on tool failures.

Reads the failed tool call from stdin, emits a short diagnostic hint as
additionalContext. Does NOT stop continuation.

Environment-specific knowledge comes from the `failure_patterns` section of the
environment catalog (hooks/_environment_catalog.py): `servers` maps an MCP
server token to its <name>-patterns.md file under the project memory dir, and
`hints` adds error-keyword -> fix entries that are checked BEFORE the built-in
generic ones below. With an empty section the hook still emits the generic
guidance; it just cannot point at a pattern file.

Exit codes:
  0 = continue (with optional additionalContext)
"""
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _environment_catalog import load_section


def _resolve_project_dir() -> Path:
    """Resolve the per-project Claude Code dir at runtime (cwd encoding)."""
    if env_dir := os.environ.get("CLAUDE_PROJECT_DIR"):
        return Path(env_dir)
    projects = Path.home() / ".claude" / "projects"
    encoded = str(Path.cwd().resolve()).replace("/", "-").replace(":", "-").strip("-")
    candidate = projects / encoded
    if candidate.exists():
        return candidate
    if projects.exists():
        subdirs = [p for p in projects.iterdir() if p.is_dir()]
        if subdirs:
            return max(subdirs, key=lambda p: p.stat().st_mtime)
    return projects / "_unresolved"


PATTERN_DIR = _resolve_project_dir() / "memory"

# Failure patterns that hold for any Claude Code host, and their fixes.
BUILTIN_PATTERNS = {
    "MaxFileReadTokenExceeded": "Use offset/limit params to paginate",
    "timeout": "Check MCP server connectivity first",
    "encoding": "Write to file first, then execute (not inline)",
    "SyntaxError": "Write to .py/.ps1 file first, don't inline complex code",
    "None": "Guard against None responses (some APIs return None instead of [])",
    "not yet populated": "Table load not complete, retry after delay",
    "Access denied": "Sub-agents can't auth to remote MCPs - run in main session",
    "404": "Check endpoint path; for GitHub private repos use gh CLI not MCP",
    "403": "Permission denied; for GitHub use gh CLI not MCP tools",
    "InputValidationError": "Tool schema evicted after autocompact. Use ToolSearch to reload the schema: select:<tool_name>",
    "Unknown tool": "Tool schema not loaded. Use ToolSearch to load it: select:<tool_name>",
    "inline-python-guard": "Write the same code to a .py file with the Write tool, then run: python script.py",
}


def load_patterns(section=None):
    """Return (PATTERNS, SERVER_TO_PATTERN) from the catalog plus the built-ins.

    The operator's hints come first so an environment-specific keyword wins over
    a generic one that also matches; a built-in keyword the operator redefines
    takes the operator's text.
    """
    if section is None:
        section = load_section("failure_patterns")
    patterns = {
        str(k): str(v) for k, v in (section.get("hints") or {}).items()
        if isinstance(k, str) and isinstance(v, str) and k
    }
    for keyword, fix in BUILTIN_PATTERNS.items():
        patterns.setdefault(keyword, fix)
    server_to_pattern = {
        str(k): str(v) for k, v in (section.get("servers") or {}).items()
        if isinstance(k, str) and isinstance(v, str) and k and v
    }
    return patterns, server_to_pattern


# Error keyword -> likely fix, and MCP server token -> pattern file name.
PATTERNS, SERVER_TO_PATTERN = load_patterns()


def detect_pattern_file(tool_name):
    """Find the pattern file for a given MCP tool name."""
    # Extract server name from tool_name like mcp__remote-edr__search_hosts
    match = re.match(r"mcp__(?:remote-)?(\w+)__", tool_name)
    if not match:
        return None
    server = match.group(1).replace("-", "").replace("_", "")

    for key, filename in SERVER_TO_PATTERN.items():
        if key in server:
            path = PATTERN_DIR / filename
            if path.exists():
                return filename
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = data.get("tool_name", "unknown")
    error = str(data.get("error", ""))[:500]

    # Find matching pattern. Word-boundary match (not bare substring) so short
    # keys don't fire inside unrelated tokens: "404" must not match "1404
    # records", "None" must not match "anyone", "LIMIT" not "UNLIMITED".
    hint = None
    for keyword, fix in PATTERNS.items():
        # Single-token identifier/constant keys (None, LIMIT, SyntaxError) match
        # case-sensitively so the Python literal `None` isn't triggered by the
        # prose word "none". Multi-word phrases stay case-insensitive.
        flags = 0 if (any(c.isupper() for c in keyword) and " " not in keyword) else re.IGNORECASE
        if re.search(r"\b" + re.escape(keyword) + r"\b", error, flags):
            hint = fix
            break

    # Build non-blocking message
    parts = [f"Tool `{tool_name}` failed."]
    if hint:
        parts.append(f"Likely fix: {hint}.")
    parts.append("Diagnose root cause before retrying.")

    # Check for relevant pattern file
    pattern_file = detect_pattern_file(tool_name)
    if pattern_file:
        parts.append(
            f"Check `memory/{pattern_file}` for known gotchas with this tool."
        )
    elif tool_name.startswith("mcp__"):
        parts.append(
            "This is an MCP tool - check if a *-patterns.md file exists for known gotchas."
        )

    msg = " ".join(parts)
    # additionalContext is the documented channel to the model; a top-level
    # "message" never reached it (live-probed 2026-09-03).
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUseFailure",
                                             "additionalContext": msg}}))
    sys.exit(0)


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
