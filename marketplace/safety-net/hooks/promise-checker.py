"""Stop hook: catches performative compliance + banned session-closure phrases.

1. Detects when Claude says "I'll remember" / "I've noted" / "saved to memory"
   without actually calling Edit/Write/memory_search tools. Blocks with exit 2.
2. Detects when Claude suggests ending the session prematurely with banned
   phrases ("let's continue in a new session", "good stopping point", etc.).
   Blocks with exit 2.

Selectively cloned from flonat/claude-research (2026-03-30).
Banned phrases inspired by SolomonikVik/svaib (2026-04-02).
Adapted from bash to Python for Windows compatibility.
"""

import json
import os
import sys

# Promise patterns - phrases where Claude claims to have stored/remembered
# something, or promises to do so.
PROMISE_PATTERNS = [
    # Future promises
    "i'll remember",
    "i'll note that",
    "i'll write that down",
    "i'll save that",
    "i'll store that",
    "i'll record that",
    "i'll keep that in mind",
    "i'll add that to memory",
    # Past claims
    "i've noted",
    "i've remembered",
    "i've saved",
    "i've stored",
    "i've recorded",
    "i've written that down",
    "i've added that to memory",
    "noted for future",
    "saved to memory",
    "stored in memory",
    "added to memory",
    "updated memory",
]

# Banned session-closure phrases — enforces never-stop-early.md via hook.
# The user called this their "#1 most frustrating behavior."
BANNED_PHRASES = [
    "let's continue this in a new session",
    "continue in a new session",
    "start a fresh session",
    "fresh session for this",
    "pick this up in a new conversation",
    "continue next time",
    "good stopping point",
    "natural stopping point",
    "let's wrap up",
    "wrap up for now",
    "we can continue next time",
    "let's pause here",
]

# Tools that count as "actually writing"
WRITE_TOOLS = {"Edit", "Write", "NotebookEdit", "mcp__memory-search__memory_search"}


def _content_blocks(entry):
    """Return a transcript entry's content as a list of typed blocks.

    Claude Code transcript JSONL nests the message under entry["message"],
    whose "content" is either a plain string (human text) or a list of typed
    blocks (text / tool_use / tool_result). A bare string is normalized to a
    single text block. Anything unexpected yields []. Matches the canonical
    accessor in subagent-stop.py.
    """
    if not isinstance(entry, dict):
        return []
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return []
    content = msg.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return content
    return []


def _is_human_turn(entry):
    """True only for a genuine human user message (the turn boundary).

    Tool results are delivered as type=="user" entries whose content is
    tool_result blocks; they must NOT end the turn, because the Write that
    fulfils a promise typically precedes its own tool_result. A real human
    turn has string content or at least one "text" block.
    """
    if not isinstance(entry, dict) or entry.get("type") != "user":
        return False
    return any(
        isinstance(b, dict) and b.get("type") == "text"
        for b in _content_blocks(entry)
    )


def main():
    # Env-var bypass — used by the /goal-vs-orchestration eval (see
    # docs/plans/2026-05-23-goal-vs-orchestration-eval-design.md) to
    # isolate native /goal behavior from this hook's enforcement.
    if os.environ.get("CLAUDE_SKIP_PROMISE_CHECKER") == "1":
        sys.exit(0)

    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, Exception):
        sys.exit(0)

    # Get transcript path from Stop hook input
    transcript_path = hook_input.get("transcript_path", "")
    if not transcript_path:
        sys.exit(0)

    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (FileNotFoundError, PermissionError, OSError):
        sys.exit(0)

    if not lines:
        sys.exit(0)

    # Walk backwards collecting the final assistant turn, stopping at the
    # previous *human* user message. Tool results arrive as type=="user"
    # entries and must not end the turn (the fulfilling Write precedes its
    # own tool_result).
    last_turn = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if _is_human_turn(entry):
            break
        last_turn.append(entry)

    if not last_turn:
        sys.exit(0)

    # A write/edit/memory tool call anywhere in this turn fulfils a promise.
    has_write = False
    for entry in last_turn:
        if entry.get("type") != "assistant":
            continue
        for block in _content_blocks(entry):
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("name", "") in WRITE_TOOLS
            ):
                has_write = True
                break
        if has_write:
            break

    # If writes happened, no need to check promises
    if has_write:
        sys.exit(0)

    # Collect the assistant's spoken text from this turn.
    text_parts = []
    for entry in last_turn:
        if entry.get("type") != "assistant":
            continue
        for block in _content_blocks(entry):
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))

    full_text = "\n".join(text_parts).lower()
    if not full_text:
        sys.exit(0)

    # Check 1: Banned session-closure phrases (no write-tool context needed)
    found_banned = []
    for phrase in BANNED_PHRASES:
        if phrase in full_text:
            found_banned.append(phrase)

    if found_banned:
        banned_str = ", ".join(f'"{p}"' for p in found_banned[:3])
        sys.stderr.write(
            f"[promise-checker] BLOCKED: Session-closure phrase detected ({banned_str}). "
            f"Per never-stop-early.md: never suggest continuing in a new session. "
            f"Continue working on the task instead.\n"
        )
        sys.exit(2)

    # Check 2: Promise patterns without corresponding writes
    found_promises = []
    for pattern in PROMISE_PATTERNS:
        if pattern in full_text:
            found_promises.append(pattern)

    if not found_promises:
        sys.exit(0)

    # Promises found without writes — block
    promises_str = ", ".join(f'"{p}"' for p in found_promises[:3])
    sys.stderr.write(
        f"[promise-checker] BLOCKED: Found promise patterns ({promises_str}) "
        f"in last assistant turn but no Edit/Write/memory tool calls were made. "
        f"Claude may have claimed to remember something without actually persisting it.\n"
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
