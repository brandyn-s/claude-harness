#!/usr/bin/env python3
r"""Decode a base64 GitHub contents-API payload from stdin to UTF-8 stdout.

Companion to scout-skills SKILL.md Step 2. The decode logic previously
lived in the doc as a multi-line inline `python3 -c` snippet, which the
deployed PreToolUse hook (bash-security-guard.py inline-python-guard,
complex inline python >300 chars) blocks before execution; per that
hook's own prescription it ships as a script instead.

Usage:
    echo "$content" | tr -d '\n' | python3 decode_contents.py

Exit codes: 0 = decoded OK, 1 = decode error (message on stderr).
"""
import base64
import io
import sys


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    raw = sys.stdin.buffer.read().decode("ascii", errors="replace")
    try:
        print(base64.b64decode(raw).decode("utf-8"))
    except Exception as e:
        print(f"DECODE ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
