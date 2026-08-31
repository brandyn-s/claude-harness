"""Session-start banner for red default-branch workflows.

Reads the state file written by bin/red-main-sweep.py (launchd, daily) —
never sweeps inline (the sweep is ~150 gh API calls). The banner is the
primary notification surface by design: three multi-week red mains went
unnoticed in 2026-05/06 (mcp-servers deploys 23d, OPA bundle 18d,
enforce-mirror 13d) because nothing the operator actually looks at daily
carried the signal. Claude Code sessions are that surface.

CLAUDE_RED_MAINS_STATE overrides the state path so tests never touch the
real ~/.claude file (the supergoal test-pollution class, fixed 2026-06-12).
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

STALE_AFTER_HOURS = 48
TOP_N = 5


def _state_path():
    override = os.environ.get("CLAUDE_RED_MAINS_STATE")
    if override:
        return Path(override)
    return Path.home() / ".claude" / "red-mains.json"


def check_red_mains():
    """Return banner lines (possibly empty) describing red mains.

    Distinguishes three states honestly:
    - state file absent      -> silent (sweeper not installed/never ran)
    - state stale (>48h)     -> staleness warning (launchd job dead?)
    - reds present           -> compact count + top entries
    An unreadable file is reported, never swallowed into silence —
    a broken monitor that looks green is the failure mode this whole
    mechanism exists to kill.
    """
    path = _state_path()
    if not path.exists():
        return []
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [f"RED-MAINS: state file unreadable ({path}) — "
                "re-run bin/red-main-sweep.py"]

    msgs = []
    gen = state.get("generated_at", "")
    try:
        age_h = (datetime.now(timezone.utc)
                 - datetime.fromisoformat(gen)).total_seconds() / 3600
    except ValueError:
        age_h = None
    if age_h is None or age_h > STALE_AFTER_HOURS:
        stamp = f"{age_h / 24:.0f}d old" if age_h is not None else "no timestamp"
        msgs.append(
            f"RED-MAINS: sweep state stale ({stamp}) — launchd job "
            "com.example.red-main-sweep may not be running")

    red = state.get("red", [])
    if red:
        top = ", ".join(
            f"{f.get('repo', '?').split('/', 1)[-1]}/{f.get('workflow', '?')}"
            for f in red[:TOP_N])
        more = f" (+{len(red) - TOP_N} more)" if len(red) > TOP_N else ""
        msgs.append(
            f"RED MAINS ({len(red)}): {top}{more} — "
            "full list: ~/.claude/red-mains.json")
    return msgs
