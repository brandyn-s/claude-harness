"""PreToolUse:Read guard for oversized partial reads of control files.

Small targeted reads are allowed. Large partial reads of settings, rules,
skills, agents, and CLAUDE.md are rejected because they are commonly followed
by edits made without the rest of the contract in view. Invalid input fails
open so the guard cannot make Read unavailable.
"""

from __future__ import annotations

import json
import re
import sys

MAX_TARGETED_LINES = 100
CONTROL_PATHS = tuple(
    re.compile(pattern)
    for pattern in (
        r"(?:^|/)CLAUDE\.md$",
        r"(?:^|/)settings(?:\.local)?\.json$",
        r"(?:^|/)rules/.*\.md$",
        r"(?:^|/)skills/[^/]+/SKILL\.md$",
        r"(?:^|/)agents/.*\.md$",
    )
)


def _relative_control_path(raw_path: object) -> str | None:
    if not isinstance(raw_path, str):
        return None
    normalized = raw_path.replace("\\", "/")
    if "/.claude/" not in normalized:
        return None
    return normalized.split("/.claude/", 1)[1]


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    tool_input = payload.get("tool_input") or {}
    offset = tool_input.get("offset")
    limit = tool_input.get("limit")
    if offset is None and limit is None:
        return 0
    if isinstance(limit, int) and 0 <= limit <= MAX_TARGETED_LINES:
        return 0

    relative = _relative_control_path(tool_input.get("file_path"))
    if relative is None or not any(pattern.search(relative) for pattern in CONTROL_PATHS):
        return 0

    print(
        "[block-partial-read] BLOCKED: large partial read "
        f"(offset={offset}, limit={limit}) on control file {relative}. "
        "Read the complete file before changing its contract.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(0)
