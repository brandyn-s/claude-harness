#!/usr/bin/env python3
"""PreToolUse:Glob|Grep hook - block overly broad search paths.

Prevents ripgrep timeouts by rejecting Glob/Grep calls that would scan
huge directory trees (home dir, C:/ root, ~/.claude/ with 150K+ files).

Exits 0 with no output to allow the call.
Exits 2 with a JSON message to block with guidance.
"""
import json
import os
import sys

# Paths that are too broad to search (case-insensitive on Windows)
BLOCKED_ROOTS = [
    os.path.expanduser("~"),           # Home dir (150K+ files)
    "C:/",                              # Entire C drive
    "C:\\",
    "/c/",                              # Git Bash mount
    "/c",
]

# Subdirs under ~/.claude that are huge
BLOCKED_SUBDIRS = [
    os.path.join(os.path.expanduser("~"), ".claude", "plugins"),
    os.path.join(os.path.expanduser("~"), ".claude", "session-transcripts"),
    os.path.join(os.path.expanduser("~"), ".claude", "cache"),
]


def normalize(p):
    """Normalize path for comparison."""
    return os.path.normpath(p).replace("\\", "/").rstrip("/").lower()


def main():
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    if tool_name not in ("Glob", "Grep"):
        sys.exit(0)

    tool_input = hook_input.get("tool_input", {})
    path = tool_input.get("path", "")

    if not path:
        # No path = cwd, which is fine if cwd is scoped
        sys.exit(0)

    norm = normalize(path)

    # Check exact match against blocked roots
    for blocked in BLOCKED_ROOTS:
        if norm == normalize(blocked):
            print(json.dumps({
                "decision": "block",
                "reason": (
                    f"Path '{path}' is too broad - ripgrep will timeout scanning "
                    f"150K+ files. Scope to a specific subdirectory (e.g., a repo "
                    f"root or ~/.claude/skills/). Use Bash 'ls' for ~/.claude/ listings."
                ),
            }))
            sys.exit(2)

    # Check blocked subdirs
    for blocked in BLOCKED_SUBDIRS:
        if norm == normalize(blocked) or norm.startswith(normalize(blocked) + "/"):
            dirname = os.path.basename(blocked)
            print(json.dumps({
                "decision": "block",
                "reason": (
                    f"Path '{path}' contains ~/.claude/{dirname}/ which has "
                    f"thousands of files. Use Bash 'ls' or 'find' for this directory, "
                    f"or scope to a specific subdirectory."
                ),
            }))
            sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
