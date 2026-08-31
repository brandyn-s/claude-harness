"""Spawn a detached background reindex for stale / identity-broken indexes.

THE GAP THIS CLOSES
-------------------
Every index-freshness path in the harness used to WARN and stop. The banner
said "Run /index-repo <repo>" and then waited for a human. On 2026-08-04 that
had accumulated nine stale graphs plus a `claude-hud` index stuck at 1 node /
0 edges with a broken git identity since 01:39 -- invisible to code search --
because one transient failure was reported once and never retried.

The MCP server does auto-sync, but only for the CURRENT session's project.
Nothing healed the other eighteen. This module generalises that to the whole
registry by handing the work to `scripts/heal-code-index.py`, detached.

WHY DETACHED, NOT INLINE
------------------------
SessionStart has a ~2s budget. Reindexing 19 projects does not fit, and a
hook that blocks startup to fix a warning is a worse failure than the
warning. The healer runs out of band; the NEXT session start sees a clean
registry. Enumeration here is a few tens of milliseconds (ref files are read
directly -- see index_staleness._head_revision_fast).

SAFETY
------
* Single-instance: the healer takes a pid lockfile. Seven concurrent Claude
  Code sessions is normal on this host and they all start at once.
* BACKOFF: if the previous run left projects unhealed, we do NOT respawn
  within AUTOHEAL_MIN_INTERVAL_SECS. A healer that cannot fix something must
  not hammer it once per session start -- that turns a stale index into a
  background-process storm.
* This module never raises: a failure to heal must not break SessionStart.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .index_staleness import _short, heal_candidates
# Reuse the CI-hardened liveness probe rather than rolling a second one:
# on Windows, os.kill(pid, 0) reports terminated-but-handle-held processes
# as alive, which would leave a dead healer's lock blocking every heal.
# concurrent_session's own windows-2022 CI leg is what found that.
from .concurrent_session import _pid_alive

CACHE_DIR = Path.home() / ".cache" / "codebase-memory-mcp"
LOCK_PATH = CACHE_DIR / ".autoheal.lock"
STATUS_PATH = CACHE_DIR / "autoheal-status.json"
HEAL_LOG = CACHE_DIR / "autoheal.log"

HEALER = (
    Path(__file__).resolve().parent.parent.parent / "scripts" / "heal-code-index.py"
)

# Do not respawn this often when the previous run left work undone. Long
# enough that a genuinely unhealable project reports instead of thrashing;
# short enough that a transient failure retries within the hour.
AUTOHEAL_MIN_INTERVAL_SECS = 900

# Opt-out for anyone who wants the warn-only behaviour back.
DISABLE_ENV = "CLAUDE_DISABLE_INDEX_AUTOHEAL"


def _healer_running() -> bool:
    try:
        data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return _pid_alive(int(data.get("pid", -1)))


def _last_run() -> dict:
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _backing_off(status: dict) -> bool:
    """True when the previous run left work undone and was too recent."""
    if not status.get("remaining"):
        return False
    ran_at = status.get("ran_at")
    if not ran_at:
        return False
    try:
        from datetime import datetime

        prev = datetime.fromisoformat(str(ran_at)).timestamp()
    except (ValueError, TypeError):
        return False
    return (time.time() - prev) < AUTOHEAL_MIN_INTERVAL_SECS


def autoheal_indexes() -> list[str]:
    """Spawn the healer if there is work. Returns banner messages."""
    if os.environ.get(DISABLE_ENV):
        return []
    try:
        candidates = heal_candidates()
    except Exception:
        # Enumeration must never break SessionStart.
        return []
    if not candidates:
        return []

    labels = sorted({_short(c["name"], c["root_path"]) for c in candidates})
    shown = ", ".join(labels[:6]) + (" …" if len(labels) > 6 else "")

    if _healer_running():
        return [f"Index autoheal: already running ({len(labels)} project(s): {shown})."]

    status = _last_run()
    if _backing_off(status):
        stuck = ", ".join(status.get("remaining", [])[:6])
        return [
            f"Index autoheal: BACKING OFF — the last run left {stuck} unhealed "
            f"and ran <{AUTOHEAL_MIN_INTERVAL_SECS // 60}m ago, so it is not "
            f"retrying automatically. These indexes are STALE. Run "
            f"`python3 {HEALER} --dry-run` to inspect, or /index-repo --audit."
        ]

    if not HEALER.is_file():
        return [
            f"Index autoheal: healer script missing at {HEALER}; "
            f"{len(labels)} stale index(es) will NOT self-heal."
        ]

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # Open the log BEFORE spawning: a redirect into a directory the child
        # is expected to create is a documented silent no-op.
        log = open(HEAL_LOG, "a", encoding="utf-8")
        subprocess.Popen(
            [sys.executable, str(HEALER)],
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            # Detach so the healer outlives this session.
            start_new_session=True,
            cwd=str(HEALER.parent.parent),
        )
    except Exception as e:  # noqa: BLE001 — never break SessionStart
        return [
            f"Index autoheal: could not start healer ({e}); "
            f"{len(labels)} stale index(es) need /index-repo."
        ]

    return [
        f"Index autoheal: reindexing {len(labels)} stale index(es) in the "
        f"background ({shown}). They should be clean next session; progress "
        f"in {HEAL_LOG}."
    ]
