#!/usr/bin/env python3
"""Count compactions per session and, at two, ask for a handoff.

THE PROBLEM
    This week's three longest arcs ran 20, 24 and 39 hours and each crossed three
    or more compactions. After a compaction only ~5,000 tokens of an invoked skill
    survive (compaction-continuity.py), the acceptance ledger has to be
    rehydrated (ledger_rehydrate.py), and the 14-day review found corrective turns
    concentrating in exactly these sessions. Three hooks exist to survive long
    sessions; none suggests ending one at a task boundary. never-stop-early.md
    (deleted 2026-09-03 for fighting outcome-over-verification) forbade the
    suggestion outright and nothing replaced the boundary half of it;
    session-boundaries.md now permits a fresh session once the handoff is
    written, and this hook is what raises it. session-start.py already reads
    ~/.claude/HANDOFF.md at the next startup and shows it once.

WHY TWO EVENTS
    PostCompact knows a compaction happened but cannot inject context (its
    stdout/systemMessage are discarded). UserPromptSubmit can. Same dispatch shape
    as compaction-continuity.py:
      PostCompact       -> increment the per-session counter; also bump the session
                           ledger's compaction_count when a ledger exists (the
                           ledger carries the field but nothing writes it)
      UserPromptSubmit  -> if count >= THRESHOLD and this count has not been
                           announced, print the handoff nudge ONCE for this count

CONTRACT
    exit 0 always (UserPromptSubmit exit 2 would erase the prompt). Never blocks.
    The nudge is advice (ARCHITECTURE.md §1: only a blocking hook enforces); the
    phrase-based Stop blocker was demoted on purpose and is not reinstated here.

STATE
    ~/.claude/run/compaction-budget/<session>.json  {"count": n, "nudged_at": m}
    written with os.replace. Threshold: CLAUDE_COMPACTION_BUDGET (default 2).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

STATE_DIR = Path.home() / ".claude" / "run" / "compaction-budget"
HOOKS_DIR = Path(__file__).resolve().parent
DEFAULT_THRESHOLD = 2


def _threshold() -> int:
    try:
        return max(1, int(os.environ.get("CLAUDE_COMPACTION_BUDGET", DEFAULT_THRESHOLD)))
    except ValueError:
        return DEFAULT_THRESHOLD


def _state_path(session_id) -> Path:
    safe = "".join(c for c in str(session_id or "") if c.isalnum() or c in "-_") or "unknown"
    return STATE_DIR / f"{safe}.json"


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path: Path, state: dict) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        print(f"compaction-budget: state write failed: {exc}", file=sys.stderr)


def _bump_ledger(session_id: str) -> None:
    """Best-effort: write the compaction_count the ledger schema already carries."""
    sys.path.insert(0, str(HOOKS_DIR))
    try:
        import session_ledger as sl  # type: ignore
        ledger = sl.load(session_id)
        if ledger is not None:
            sl.save(sl.mark_compaction(ledger))
    except Exception:
        pass


def on_post_compact(payload: dict) -> int:
    sid = str(payload.get("session_id") or "unknown")
    path = _state_path(sid)
    state = _load(path)
    state["count"] = int(state.get("count", 0)) + 1
    state["last_trigger"] = payload.get("trigger")
    state["last_at_utc"] = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    state.setdefault("nudged_at", 0)
    _save(path, state)
    _bump_ledger(sid)
    return 0


NUDGE = (
    "<compaction-budget>\n"
    "This session has compacted {count} time(s) (last: {trigger}, {at}). Per session_boundaries:\n"
    "- If the framed task's done-criteria are met and evidenced: report the evidence and stop. "
    "The next task gets a fresh session and its own frame.\n"
    "- Otherwise: write HANDOFF.md in the working directory - objective and INTENT link; what is "
    "done, with evidence paths; open items and the exact next executable action; decisions and "
    "cuts since the last handoff; files touched; rollback point; first thing to verify - copy it "
    "to ~/.claude/HANDOFF.md (session-start shows that file once at the next startup), then "
    "propose a fresh session that starts from it. Keep working until the user answers.\n"
    "Do not stop merely because the session is long. The handoff is how the next session starts "
    "clean, not a reason to abandon this one. If a skill is mid-procedure, re-invoke it first.\n"
    "</compaction-budget>"
)


def on_user_prompt_submit(payload: dict) -> int:
    sid = str(payload.get("session_id") or "unknown")
    path = _state_path(sid)
    state = _load(path)
    count = int(state.get("count", 0))
    if count < _threshold() or int(state.get("nudged_at", 0)) >= count:
        return 0
    state["nudged_at"] = count
    _save(path, state)
    print(NUDGE.format(count=count, trigger=state.get("last_trigger") or "unknown",
                       at=state.get("last_at_utc") or "unknown"))
    return 0


def main() -> int:
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
    except Exception as exc:  # never let this hook erase a prompt
        print(f"compaction-budget: {exc}", file=sys.stderr)
        sys.exit(0)
