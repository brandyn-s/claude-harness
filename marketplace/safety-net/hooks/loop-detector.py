#!/usr/bin/env python3
"""ASI08: Cascading Failure Prevention - Loop Detector.

PostToolUse hook that maintains a session-scoped ring buffer of recent
tool calls and detects:
- No-op loops: same tool + same args repeated >=3 times
- Retry storms: same tool, all failing, >=4 times

Non-blocking (always exit 0). Emits hookSpecificOutput.additionalContext to redirect the agent (systemMessage only reached the user).
"""

import hashlib
import json
import os
import sys
from pathlib import Path

SESSION_ENV_DIR = Path.home() / ".claude" / "session-env"
RING_BUFFER_SIZE = 15
NOOP_THRESHOLD = 3
RETRY_STORM_THRESHOLD = 4


def get_session_id(hook_input):
    """Extract session ID from hook input or environment."""
    sid = hook_input.get("session_id", "")
    if not sid:
        sid = os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CLAUDE_CODE_SESSION_ID", "unknown")
    return sid


def hash_input(tool_input):
    """Deterministic hash of tool input dict."""
    try:
        return hashlib.md5(
            json.dumps(tool_input, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:12]
    except (TypeError, ValueError):
        return "unhashable"


def load_history(session_id):
    """Load tool call history for this session."""
    history_file = SESSION_ENV_DIR / f"tool-history-{session_id}.json"
    if history_file.exists():
        try:
            with open(history_file, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"calls": []}


def save_history(session_id, history):
    """Save tool call history, maintaining ring buffer size.

    Atomic write: PostToolUse hooks for PARALLEL tool calls in the same
    session run concurrently, so two loop-detector processes can
    read-modify-write this file at once. A raw open('w') interleaving
    corrupts the JSON; load_history() then silently resets to empty and
    real loops go undetected. atomic_write (temp + fsync + os.replace)
    makes each writer's snapshot all-or-nothing. (B3 review, 2026-06-10;
    same convention as the other per-session state hooks.)
    """
    SESSION_ENV_DIR.mkdir(parents=True, exist_ok=True)
    history["calls"] = history["calls"][-RING_BUFFER_SIZE:]
    history_file = SESSION_ENV_DIR / f"tool-history-{session_id}.json"
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from atomic_write import atomic_write
        atomic_write(history_file, json.dumps(history))
    except Exception:
        # Fall back to plain write if atomic_write isn't importable —
        # degraded detection beats a crashed hook.
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history, f)


def check_noop_loop(calls):
    """Check if the last N calls are identical (same tool + same input hash)."""
    if len(calls) < NOOP_THRESHOLD:
        return None

    latest = calls[-1]
    key = (latest["tool"], latest["input_hash"])

    count = 0
    for call in reversed(calls):
        if (call["tool"], call["input_hash"]) == key:
            count += 1
        else:
            break

    if count >= NOOP_THRESHOLD:
        return {
            "type": "noop_loop",
            "tool": latest["tool"],
            "count": count,
        }
    return None


def check_retry_storm(calls):
    """Check if the last N calls to the same tool all failed."""
    if len(calls) < RETRY_STORM_THRESHOLD:
        return None

    latest = calls[-1]
    if not latest.get("is_error"):
        return None

    tool = latest["tool"]
    fail_count = 0
    for call in reversed(calls):
        if call["tool"] == tool and call.get("is_error"):
            fail_count += 1
        else:
            break

    if fail_count >= RETRY_STORM_THRESHOLD:
        return {
            "type": "retry_storm",
            "tool": tool,
            "count": fail_count,
        }
    return None


def _derive_is_error(hook_input):
    """Determine whether the tool call failed.

    The top-level "is_error" key is NOT set by current Claude Code on
    PostToolUse, so the retry-storm detector never fired. The outcome lives
    in the result payload, delivered under tool_response (canonical) /
    tool_result / response. Prefer structured signals; fall back to a
    conservative string check to avoid false retry-storm warnings.
    (Note: if a runtime routes failures only to PostToolUseFailure, retry-storm
    should also be wired there — tracked as a follow-up.)
    """
    if hook_input.get("is_error") is True:
        return True
    resp = (
        hook_input.get("tool_response")
        or hook_input.get("tool_result")
        or hook_input.get("response")
    )
    if isinstance(resp, dict):
        if resp.get("is_error") is True or resp.get("error"):
            return True
        status = resp.get("status") or resp.get("type")
        if isinstance(status, str) and status.lower() in ("error", "failed", "failure"):
            return True
    elif isinstance(resp, str):
        head = resp.lstrip()[:80].lower()
        if head.startswith("error") or "traceback (most recent call last)" in resp.lower():
            return True
    return False


def main():
    # Fast-path: at low effort, the user is iterating fast and accepts
    # missing the occasional retry-storm signal in exchange for ~10-20ms
    # off every tool call. Honors $CLAUDE_EFFORT set by /effort low
    # (v2.1.128+). Non-blocking exit.
    if os.environ.get("CLAUDE_EFFORT") == "low":
        sys.exit(0)

    raw = sys.stdin.read()
    try:
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})
    is_error = _derive_is_error(hook_input)
    session_id = get_session_id(hook_input)

    # Record this call
    history = load_history(session_id)
    history["calls"].append(
        {
            "tool": tool_name,
            "input_hash": hash_input(tool_input),
            "is_error": is_error,
        }
    )
    save_history(session_id, history)

    # Check for failure patterns
    warnings = []

    loop = check_noop_loop(history["calls"])
    if loop:
        warnings.append(
            f"LOOP DETECTED: You have called {loop['tool']} with identical arguments "
            f"{loop['count']} times consecutively. The result will not change. "
            f"Try a different approach or ask the user for guidance."
        )

    storm = check_retry_storm(history["calls"])
    if storm:
        warnings.append(
            f"RETRY STORM: {storm['tool']} has failed {storm['count']} times in a row. "
            f"Stop retrying and diagnose the root cause. Check error messages, "
            f"verify parameters, or try an alternative tool."
        )

    if warnings:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": " | ".join(warnings)}}))

    sys.exit(0)  # Always non-blocking


if __name__ == "__main__":
    # crash-safety: wrap main() so an unhandled exception exits 0
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.exit(0)
