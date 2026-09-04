"""Shared manifest metrics logging for hooks.

Fire-and-forget JSONL logging for manifest query usage and advisory
hook compliance tracking. Used by all manifest-integrated hooks.

Logs to:
  ~/.claude/audit/manifest-queries-{date}.jsonl   — hook usage patterns
  ~/.claude/audit/manifest-compliance-{date}.jsonl — advisory effectiveness
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

AUDIT_DIR = Path.home() / ".claude" / "audit"
SESSION_ENV_DIR = Path.home() / ".claude" / "session-env"

# In-process block tally used instead of the on-disk marker under test mode, so
# a fixture still gets a plausible int without leaving session state behind.
_TEST_BLOCKS: dict[str, int] = {}


def _session_key(session_id=None, default="default"):
    """12-char session key for on-disk markers and log rows.

    Claude Code delivers `session_id` in the hook's stdin payload; it does NOT
    export CLAUDE_SESSION_ID / CLAUDE_CODE_SESSION_ID to hook processes (docs,
    verified 2026-09-03). Keying on the env vars alone therefore merged every
    real session into one `...-default.json`, which turned the "blocked N TIMES
    THIS SESSION" banner into a lifetime counter. Callers pass the payload id;
    the env vars remain as a fallback for launchers that do export them.
    """
    sid = (
        session_id
        or os.environ.get("CLAUDE_SESSION_ID")
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or default
    )
    return str(sid)[:12]


def _test_mode():
    """True when running under the test suite.

    Every writer below is session-scoped state, and pytest subprocesses inherit
    CLAUDE_SESSION_ID from the parent, so without this the suite writes into the
    LIVE session's counters. bash-security-guard.py's _audit_log has honoured
    this variable all along, which is exactly why its audit log stayed accurate
    while these markers did not.

    Measured 2026-08-29: one run of test_bash_security_guard.py injected 97
    phantom blocks. A real session's escalation banner reported 2, then 201,
    then 396 blocks while its transcript contained 4 -- the jumps were two test
    runs, not two hundred blocks.
    """
    return bool(os.environ.get("CLAUDE_HOOK_TEST"))


def _ensure_audit_dir():
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def log_manifest_query(hook_name, query_type, result_summary, used_fallback=False,
                       session_id=None):
    """Log a manifest graph query from a hook.

    Args:
        hook_name: e.g. "pre-agent-dispatch", "auto-topic-loader"
        query_type: e.g. "auth_enrichment", "topic_derivation", "auth_check"
        result_summary: brief description of what the query returned
        used_fallback: True if fell back to non-manifest code path
        session_id: the payload's session_id (preferred over env vars)
    """
    if _test_mode():
        return
    try:
        _ensure_audit_dir()
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = AUDIT_DIR / f"manifest-queries-{date}.jsonl"
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "hook": hook_name,
            "query_type": query_type,
            "result": result_summary[:200],
            "used_fallback": used_fallback,
            "session": _session_key(session_id, default="unknown"),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:  # noqa: S110, BLE001 -- fail-open: telemetry is fire-and-forget
        pass  # Fire-and-forget


def log_advisory_warning(hook_name, tool_name, operation, warned=True, session_id=None):
    """Log when an advisory hook fires a warning.

    Args:
        hook_name: e.g. "security-write-confirm", "pre-agent-dispatch"
        tool_name: the MCP tool or tool type that triggered the warning
        operation: what the tool was doing (e.g. "assign_alert", "dispatch agent")
        warned: True if warning was emitted (write detected), False if passed (read)
        session_id: the payload's session_id (preferred over env vars)
    """
    if _test_mode():
        return
    try:
        _ensure_audit_dir()
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = AUDIT_DIR / f"manifest-compliance-{date}.jsonl"
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "hook": hook_name,
            "tool": tool_name,
            "operation": operation,
            "warned": warned,
            "session": _session_key(session_id, default="unknown"),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:  # noqa: S110, BLE001 -- fail-open: telemetry is fire-and-forget
        pass  # Fire-and-forget


def get_session_warning_count(hook_name, session_id=None):
    """Get warning count for a hook in the current session. For compliance tracking."""
    marker = SESSION_ENV_DIR / f"advisory-{hook_name}-{_session_key(session_id)}.json"
    if marker.exists():
        try:
            return json.loads(marker.read_text(encoding="utf-8"))
        except Exception:  # noqa: S110, BLE001 -- fail-open: an unreadable marker yields the default counts
            pass  # fail-open: fall through to the default counts
    return {"warnings": 0, "complied": 0, "ignored": 0}


def increment_warning(hook_name, session_id=None):
    """Increment warning count for current session."""
    if _test_mode():
        return
    SESSION_ENV_DIR.mkdir(parents=True, exist_ok=True)
    marker = SESSION_ENV_DIR / f"advisory-{hook_name}-{_session_key(session_id)}.json"
    counts = get_session_warning_count(hook_name, session_id)
    counts["warnings"] += 1
    marker.write_text(json.dumps(counts), encoding="utf-8")


# --------------------------------------------------------------------------
# Repeat-block escalation
#
# A PreToolUse guard rejects a SHAPE, and the verdict is DETERMINISTIC -- the guard
# has no memory to wear down. So the SECOND block from the same guard in one session
# is not bad luck; it is evidence the shape was re-issued rather than adapted, and the
# first message did not land.
#
# Measured 2026-07-31..08-02 in one session: bash-tail-buffering-guard blocked 30
# times and bash-security-guard 25 -- together 37% of every error in the session, all
# on shapes already documented in platform-constraints.md. Each was a wasted
# round-trip against a guard that was never going to relent.
#
# This changes only the MESSAGE, never whether something blocks, so it cannot alter
# any guard's block rate and needs no replay measurement to ship.
# --------------------------------------------------------------------------

def record_block(hook_name, session_id=None):
    """Count a BLOCK (not an advisory warning) for this hook this session.

    Returns the new total. Kept separate from `warnings` because a warning is
    advisory and a block is terminal -- conflating them would make the escalation
    fire on advisories that the model correctly proceeded past.
    """
    if _test_mode():
        # Per-process, so a fixture never reaches 2 and the escalation stays
        # silent under test -- but the return value is still a real count.
        _TEST_BLOCKS[hook_name] = _TEST_BLOCKS.get(hook_name, 0) + 1
        return _TEST_BLOCKS[hook_name]
    SESSION_ENV_DIR.mkdir(parents=True, exist_ok=True)
    marker = SESSION_ENV_DIR / f"advisory-{hook_name}-{_session_key(session_id)}.json"
    counts = get_session_warning_count(hook_name, session_id)
    counts["blocks"] = counts.get("blocks", 0) + 1
    marker.write_text(json.dumps(counts), encoding="utf-8")
    return counts["blocks"]


def repeat_escalation(hook_name, remedy="", session_id=None):
    """Record a block and return an escalation note for the 2nd+ block this session.

    Returns "" on the first block so a one-off block reads exactly as it does today.
    `session_id` is the hook payload's session_id; without it the counter falls back
    to env vars and then to a shared "default" bucket, which is exactly the lifetime
    counter this parameter exists to prevent.
    """
    try:
        n = record_block(hook_name, session_id)
    except Exception:
        return ""
    if n < 2:
        return ""
    tail = f"  {remedy}" if remedy else ""
    return (
        f"\n\n*** {hook_name} has now blocked {n} TIMES THIS SESSION. ***\n"
        "This verdict is deterministic. Re-issuing the same SHAPE with different\n"
        "CONTENT will be blocked again -- the guard matches your command text, not\n"
        "your intent, and it has no memory to wear down. Change the SHAPE now."
        f"{tail}"
    )
