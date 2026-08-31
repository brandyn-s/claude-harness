"""Canonical accessors for Claude Code hook input.

Hook input schemas drifted over time and across hook authors, producing
the silent-no-op bug class fixed in the 2026-05-23 audit:

- PreToolUse: 3 hooks read `data.get("input")` instead of the canonical
  `data.get("tool_input")` — security-write-confirm, verify-before-assuming,
  pre-agent-dispatch all silently no-op'd on every call.
- PostToolUse: 3 different field names used across 7+ hooks — `tool_result`,
  `tool_response`, and bare `response`. Only one is canonical at any
  given Claude Code version; the others returned empty strings.
- SubagentStop: 1 hook (subagent-stop) read `data.get("transcript")` for
  inline content instead of `data.get("transcript_path")` for the file
  path — the learnings-capture block never fired in production.

This module collapses the schema knowledge into one place. New hooks
should import these accessors and stop maintaining per-hook key fallback
chains.

Usage:

    from hook_input import tool_input, tool_response, transcript_text

    def main():
        data = json.load(sys.stdin)
        params = tool_input(data)            # PreToolUse params dict
        body = tool_response(data)           # PostToolUse result/response
        transcript = transcript_text(data)   # SubagentStop transcript content

Each accessor:
- Tries the canonical key first (per current Claude Code docs)
- Falls back to historic alternates for forward-and-backward compat
- Never raises; returns the documented empty default if all keys missing
- Has its own regression test in test_hook_input.py
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def tool_input(data: dict) -> dict:
    """Return the tool_input dict for PreToolUse / PostToolUse hooks.

    Canonical key: `tool_input`. Legacy key some early hooks read: `input`.
    Returns `{}` if neither key is present or its value isn't a dict.
    """
    if not isinstance(data, dict):
        return {}
    value = data.get("tool_input")
    if not isinstance(value, dict):
        value = data.get("input")
    return value if isinstance(value, dict) else {}


def tool_response(data: dict) -> Any:
    """Return the tool's output for PostToolUse hooks.

    Canonical key (current Claude Code): `tool_response`. Some legacy hooks
    read `tool_result` or bare `response`. Returns the first key present, or "" if all
    missing. Does NOT coerce the type — callers must handle dict-or-str.
    """
    if not isinstance(data, dict):
        return ""
    for key in ("tool_response", "tool_result", "response"):
        if key in data:
            return data[key]
    return ""


def tool_response_str(data: dict) -> str:
    """Like tool_response() but always returns a string. Useful for hooks
    that grep the body — JSON-encodes dict/list responses so substring
    checks still work."""
    raw = tool_response(data)
    if isinstance(raw, str):
        return raw
    if raw == "" or raw is None:
        return ""
    import json
    try:
        return json.dumps(raw, default=str)
    except (TypeError, ValueError):
        return str(raw)


def tool_name(data: dict) -> str:
    """Return the tool_name, or "" if absent. Standardize on string type."""
    if not isinstance(data, dict):
        return ""
    name = data.get("tool_name", "")
    return name if isinstance(name, str) else ""


def transcript_text(data: dict, max_bytes: int = 0) -> str:
    """Return the transcript content for Stop/SubagentStop hooks.

    Canonical schema sends `transcript_path` (a filesystem path) so the
    hook reads the file. A few callers (notably tests) inline the content
    under `transcript` — supported as a fallback.

    Args:
        data: hook input
        max_bytes: cap on bytes read from disk. 0 = read all. Use a cap
            on hooks that just need a recent slice; a 50MB transcript
            shouldn't OOM a hook that only inspects the last few KB.

    Returns "" on any error reading the file. Never raises.
    """
    if not isinstance(data, dict):
        return ""
    path = data.get("transcript_path")
    if isinstance(path, str) and path:
        try:
            p = Path(path)
            if max_bytes > 0:
                size = p.stat().st_size
                with p.open("r", encoding="utf-8", errors="replace") as f:
                    if size > max_bytes:
                        f.seek(size - max_bytes)
                    return f.read()
            return p.read_text(encoding="utf-8", errors="replace")
        except (OSError, UnicodeDecodeError):
            pass
    # Fallback: inline content.
    inline = data.get("transcript", "")
    return inline if isinstance(inline, str) else ""


def session_id(data: dict) -> str:
    """Return the session_id (or empty string)."""
    if not isinstance(data, dict):
        return ""
    sid = data.get("session_id", "")
    return sid if isinstance(sid, str) else ""


def cwd(data: dict) -> str:
    """Return the cwd (working directory) Claude is currently in."""
    if not isinstance(data, dict):
        return ""
    c = data.get("cwd", "")
    return c if isinstance(c, str) else ""
