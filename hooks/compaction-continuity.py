#!/usr/bin/env python3
"""Carry a re-invoke reminder across a compaction boundary.

THE PROBLEM
    After auto-compaction Claude Code reattaches only the first ~5,000 tokens of
    each invoked skill, inside a 25,000-token newest-first budget. A large skill
    therefore loses its TAIL across a boundary -- and for procedural skills the
    tail is where the gates live (verify, apply, persist, codify). Anthropic
    documents re-invoking the skill as the fix, but nothing prompts for it, so the
    remaining turns run against a truncated procedure that still looks complete.

WHY TWO EVENTS
    PostCompact is the event that knows a compaction happened, but it cannot say
    anything: per the hooks contract ("Exit code 2 behavior per event", read
    2026-08-21) PostCompact is `Can block? No -- shows stderr to user only`, its
    section states "PostCompact hooks have no decision control", and its
    `systemMessage` is discarded. So it cannot inject context.

    UserPromptSubmit CAN: it is one of the three events whose plain-text stdout is
    "added as context that Claude can see and act on."

    So this one script runs on BOTH events and dispatches on hook_event_name:
      PostCompact       -> drop a marker naming the session and trigger
      UserPromptSubmit  -> if a marker exists, emit the reminder ONCE, then
                           delete the marker so it never repeats

CONTRACT
    exit 0 always. On UserPromptSubmit a non-zero exit would ERASE the user's
    prompt (that event blocks on exit 2), so every path here is guarded and
    returns 0 -- a continuity nudge must never be able to eat a prompt.

INTERRUPTION: safe -- one marker file per session, written with os.replace and
deleted with missing_ok. A kill between read and unlink re-emits the reminder on
the next prompt, which is idempotent noise, not lost state.
"""
import datetime as _dt
import json
import os
import sys
from pathlib import Path

MARKER_DIR = Path.home() / ".claude" / "run" / "compaction"


def _marker(session_id):
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "-_") or "unknown"
    return MARKER_DIR / f"{safe}.json"


def on_post_compact(payload):
    """Record that a compaction happened. Cannot inject; only persists state."""
    path = _marker(payload.get("session_id"))
    record = {
        "session_id": payload.get("session_id"),
        "trigger": payload.get("trigger"),
        "at_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "summary_chars": len(payload.get("compact_summary") or ""),
    }
    try:
        MARKER_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        print(f"compaction-continuity: marker write failed: {exc}", file=sys.stderr)
    return 0


def on_user_prompt_submit(payload):
    """Emit the reminder once, then clear the marker."""
    path = _marker(payload.get("session_id"))
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return 0                                  # no compaction pending
    try:
        rec = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        rec = {}
    try:
        path.unlink(missing_ok=True)              # fire once
    except OSError:
        pass

    trigger = rec.get("trigger") or "unknown"
    at = rec.get("at_utc") or "just now"
    # stdout on UserPromptSubmit becomes context Claude can act on.
    print(
        "<compaction-continuity>\n"
        f"This session crossed a compaction boundary ({trigger}, {at}).\n"
        "Claude Code reattaches only the first ~5,000 tokens of each invoked "
        "skill after compaction, so a large skill's LATER steps -- verification, "
        "apply, persistence checks, codification -- may no longer be in context "
        "even though its opening steps are.\n"
        "Before continuing a skill-driven procedure, re-invoke the skill "
        "(e.g. /<skill-name>) to restore its full body. Do not reconstruct the "
        "remaining steps from memory or from the compaction summary.\n"
        "If no skill is active, ignore this.\n"
        "</compaction-continuity>"
    )
    return 0


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    event = payload.get("hook_event_name")
    if event == "PostCompact":
        return on_post_compact(payload)
    if event == "UserPromptSubmit":
        return on_user_prompt_submit(payload)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # UserPromptSubmit blocks on exit 2 -- never let this erase a prompt.
        print(f"compaction-continuity: {exc}", file=sys.stderr)
        sys.exit(0)
