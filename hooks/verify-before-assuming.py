"""PreToolUse hook: detect "unavailable" claims without prior verification.

Enforces the verify-before-assuming rule by scanning for patterns where
the agent claims a tool, MCP server, or capability is unavailable without
having run ToolSearch or checked the deferred tools list first.

Watches two tool types:
1. Agent dispatch prompts that contain "unavailable", "not possible",
   "can't do", "out of scope" — warns if no ToolSearch was run recently
2. Skill invocations that skip steps citing unavailability — warns to verify

Non-blocking (exit 0 + systemMessage). The agent should verify before
assuming, not be blocked from proceeding.

Exit codes:
  0 = allow (with optional systemMessage warning)
"""

import json
import os
import re
import sys
from pathlib import Path

SESSION_ENV_DIR = Path.home() / ".claude" / "session-env"

# Patterns indicating an "unavailable" claim
UNAVAILABLE_PATTERNS = re.compile(
    r"\b(unavailable|not available|not possible|can(?:'|no)t (?:do|access|use|find|connect)"
    r"|out of scope|doesn(?:'|no)t exist|no (?:tool|mcp|server) (?:for|exists)"
    r"|skip(?:ping)? (?:because|since|as) .{0,30}(?:unavailable|missing|not (?:found|installed)))\b",
    re.IGNORECASE,
)

# Patterns that indicate the claim IS verified (prior evidence)
VERIFIED_PATTERNS = re.compile(
    r"\b(ToolSearch|toolsearch|tool_search|deferred.tools|checked|verified|confirmed"
    r"|returned empty|not in .{0,20}list|tested|ran .{0,10}and)\b",
    re.IGNORECASE,
)


def _get_session_marker(session_id=None):
    """Track whether ToolSearch was used recently in this session.

    `session_id` is the hook payload's id (env vars are only a fallback).
    """
    sid = str(session_id or os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "default")
    SESSION_ENV_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_ENV_DIR / f"toolsearch-used-{sid[:12]}.flag"


def _toolsearch_was_used(session_id=None):
    """Check if ToolSearch has been called in this session."""
    marker = _get_session_marker(session_id)
    return marker.exists()


def _mark_toolsearch_used(session_id=None):
    """Record that ToolSearch was called."""
    marker = _get_session_marker(session_id)
    marker.write_text("1", encoding="utf-8")


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    # Claude Code's PreToolUse hook input uses `tool_input`. Some legacy
    # hooks read `input`, which silently no-op'd the check. Prefer the
    # canonical key; fall back to `input` for any caller still using it.
    tool_input = data.get("tool_input") or data.get("input") or {}
    session_id = data.get("session_id") or None

    # Track ToolSearch usage
    if tool_name == "ToolSearch":
        _mark_toolsearch_used(session_id)
        sys.exit(0)

    # Only check Agent and Skill tool calls
    if tool_name not in ("Agent", "Skill"):
        sys.exit(0)

    # Get the relevant text to scan
    if tool_name == "Agent":
        text = tool_input.get("prompt", "")
    elif tool_name == "Skill":
        text = tool_input.get("args", "")
    else:
        text = ""

    if not text or len(text) < 20:
        sys.exit(0)

    # Check for unavailable claims
    unavailable_match = UNAVAILABLE_PATTERNS.search(text)
    if not unavailable_match:
        sys.exit(0)

    # Check if the claim appears to be verified
    if VERIFIED_PATTERNS.search(text):
        sys.exit(0)  # Agent is citing evidence, not assuming

    # Check if ToolSearch was used this session
    if _toolsearch_was_used(session_id):
        sys.exit(0)  # ToolSearch was run — agent likely verified

    matched = unavailable_match.group()

    # Log the advisory warning
    try:
        from manifest_metrics import log_advisory_warning, increment_warning
        log_advisory_warning("verify-before-assuming", tool_name, f"claimed: {matched}",
                             warned=True, session_id=session_id)
        increment_warning("verify-before-assuming", session_id=session_id)
    except Exception:
        pass

    msg = (
        f"Verify-before-assuming: detected '{matched}' claim without prior "
        f"ToolSearch in this session. Per the verify-before-assuming rule, "
        f"'unavailable' claims require evidence — run ToolSearch or check "
        f"the deferred tools list before claiming a capability doesn't exist."
    )
    print(json.dumps({"systemMessage": msg}))
    sys.exit(0)


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)