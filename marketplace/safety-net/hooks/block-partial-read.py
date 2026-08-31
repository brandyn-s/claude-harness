"""PreToolUse:Read hook: blocks partial reads of critical config files.

Forces full file reads on files where incomplete context causes edit failures.
When offset or limit is set on a protected file, blocks with exit 2 and a
message explaining why the full read is required.

Selectively cloned from brunoldqueiroz/marvin (2026-03-30).
Adapted from bash to Python for Windows compatibility.

Protected files:
- CLAUDE.md, settings.json, settings.local.json
- rules/*.md, skills/*/SKILL.md, agents/*.md
"""

import json
import os
import re
import sys

# Protected path patterns (relative to .claude/)
PROTECTED_PATTERNS = [
    r"CLAUDE\.md$",
    r"settings\.json$",
    r"settings\.local\.json$",
    r"rules/.*\.md$",
    r"skills/.*/SKILL\.md$",
    r"agents/.*\.md$",
]


def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        sys.exit(0)

    tool_input = hook_input.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    offset = tool_input.get("offset")
    limit = tool_input.get("limit")

    # Only check if offset or limit are set (partial read)
    if offset is None and limit is None:
        sys.exit(0)

    # Targeted-read carve-out: a bounded read of <=100 lines at ANY offset is a
    # section lookup, not edit-from-incomplete-context. This aligns with the
    # search-efficiency rule (targeted partial reads are explicitly endorsed)
    # and is redundant-safe — the harness read-before-edit gate is the real
    # protection against stale edits. 2026-06-27 friction audit: the old
    # offset==0-only, limit<=50 carve-out false-blocked 187 targeted lookups in
    # 14 days (e.g. Read(rules/x.md, offset=205, limit=10)). Only large or
    # unbounded partials (a big mid-file chunk) still block.
    normalized_limit = limit if limit is not None else 9_999_999
    if normalized_limit <= 100:
        sys.exit(0)

    # Normalize to forward slashes and check if inside .claude/
    norm_path = file_path.replace("\\", "/")
    rel_path = ""

    # Extract relative path after .claude/
    if "/.claude/" in norm_path:
        rel_path = norm_path.split("/.claude/", 1)[1]
    elif "\\.claude\\" in file_path:
        rel_path = file_path.split("\\.claude\\", 1)[1].replace("\\", "/")

    if not rel_path:
        sys.exit(0)

    # Check against protected patterns
    for pattern in PROTECTED_PATTERNS:
        if re.search(pattern, rel_path):
            sys.stderr.write(
                f"[block-partial-read] BLOCKED: Partial read (offset={offset}, "
                f"limit={limit}) on critical file: {rel_path}. "
                f"Read the full file to avoid editing with incomplete context.\n"
            )
            sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)