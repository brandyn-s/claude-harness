"""Kill stale code-search / code-graph MCP server processes at SessionStart.

Each Claude Code restart spawns NEW MCP server processes. The previous
session's MCPs are SUPPOSED to terminate when their stdio transport
closes, but in practice they sometimes persist (slow daemon-thread
cleanup, leaked file handles, MCP stdio reconnect-gap bug). The leftover
processes hold SQLite WAL/SHM/fts5 file locks and block the next
reindex (WinError 32 on Windows; on macOS/Linux they squat on the WAL
and leak RAM).

This hook fires preemptively at SessionStart. The current session's MCPs
were spawned by Claude Code seconds before this hook runs, so a young
process (under `STALE_THRESHOLD_SECS`) is always kept.

Age alone is NOT sufficient to declare a process stale: with multiple
concurrent Claude Code sessions, OTHER live sessions' MCPs are hours old
and perfectly healthy. 2026-06-12 incident: every new session start
(including headless `claude -p` runs) killed every concurrent session's
codebase-memory-mcp instance — 35 forced restarts in ~28h — because the
classifier treated "older than 60s" as "from a dead session." On POSIX a
process is stale only if it is old AND orphaned (its ancestor chain
contains no live `claude` process; true zombies get re-parented toward
PID 1 when their session dies).

Detection — Windows: pwsh `Get-CimInstance Win32_Process` filtered by
CommandLine pattern; CreationDate gives the age; age-only classification
is retained there (Windows doesn't reliably preserve the parent-PID chain
across pythonw spawns). macOS/Linux: `ps -xo pid=,ppid=,etime=,command=`
(own-user processes only) filtered by command-line pattern; etime gives
the age and a full `ps -axo pid=,ppid=,comm=` snapshot supports the
live-claude-ancestor walk.

Reference: `~/.claude/rules/diagnose-before-fix.md` STEP_1b documents
the diagnostic version of this triage; this hook is the structural
preemptive fix.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _startupinfo():
    """STARTUPINFO that hides any window a console child briefly renders.
    Belt-and-suspenders with CREATE_NO_WINDOW per hook-design-patterns.md
    (2026-02-25): CREATE_NO_WINDOW prevents console allocation; SW_HIDE hides
    any window taskkill.exe renders before the flag takes effect."""
    if sys.platform != "win32":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    return si


# MCPs older than this are considered from a prior session.
# Current session's MCPs are typically 0-30s old at SessionStart hook time.
STALE_THRESHOLD_SECS = 60

# CommandLine substrings that identify each MCP server, per platform. The
# pwsh -like match is case-insensitive on Windows; substrings stay loose on
# purpose so they survive minor invocation differences (uv vs venv, .exe vs
# .py). POSIX paths use forward slashes and the code-graph binary has no
# .exe suffix.
_MCP_PATTERNS_WIN = [
    ("code-search", "code-search\\\\mcp_server\\\\server.py"),
    ("code-search-alt", "code_search\\\\mcp_server\\\\server.py"),  # underscored variant
    ("code-graph", "codebase-memory-mcp.exe"),
]
_MCP_PATTERNS_POSIX = [
    ("code-search", "code-search/mcp_server/server.py"),
    ("code-search-alt", "code_search/mcp_server/server.py"),  # underscored variant
    ("code-graph", "codebase-memory-mcp"),
]


def _mcp_patterns() -> list[tuple[str, str]]:
    """Resolve patterns at call time so tests can monkeypatch sys.platform."""
    return _MCP_PATTERNS_WIN if sys.platform == "win32" else _MCP_PATTERNS_POSIX


# Path to the marker file the hook writes for diagnostics. Each run
# overwrites the prior content.
LAST_RUN_MARKER = Path.home() / ".claude" / ".last-mcp-zombie-cleanup.json"


def _parse_etime_seconds(etime: str) -> int | None:
    """Parse ps(1) etime ([[dd-]hh:]mm:ss) into elapsed seconds.

    Returns None on malformed input — callers skip the row rather than
    guessing an age (a wrong age is what kills the live session's MCP).
    """
    etime = etime.strip()
    days = 0
    if "-" in etime:
        day_part, _, etime = etime.partition("-")
        try:
            days = int(day_part)
        except ValueError:
            return None
    parts = etime.split(":")
    if len(parts) == 2:
        h, (m, s) = 0, parts
    elif len(parts) == 3:
        h, m, s = parts
    else:
        return None
    try:
        return days * 86400 + int(h) * 3600 + int(m) * 60 + int(s)
    except ValueError:
        return None


def _list_processes_win(pattern: str) -> list[dict]:
    """Windows: pwsh Get-CimInstance Win32_Process. Returns [] on any
    failure (pwsh missing, permission denied, no matches) — never raises."""
    cmd = (
        "Get-CimInstance Win32_Process | "
        f"Where-Object {{ $_.CommandLine -like '*{pattern}*' }} | "
        "Select-Object ProcessId, "
        "@{Name='Created';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}} | "
        "ConvertTo-Json -Compress"
    )
    try:
        r = subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []
    if r.returncode != 0:
        return []
    out = r.stdout.decode("utf-8", errors="replace").strip()
    if not out:
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    # pwsh ConvertTo-Json returns a single object when one row, list when many.
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    out_rows = []
    for row in data:
        if not isinstance(row, dict):
            continue
        pid = row.get("ProcessId")
        created = row.get("Created")
        if pid is None or not created:
            continue
        out_rows.append({"pid": int(pid), "created": str(created)})
    return out_rows


def _process_snapshot() -> dict[int, tuple[int, str]]:
    """POSIX: one-shot {pid: (ppid, comm-basename)} map for ancestry walks.
    Returns {} on any failure — callers then leave ancestry UNKNOWN, which
    classifies as current (never kill on missing evidence)."""
    try:
        r = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,comm="],
            capture_output=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {}
    if r.returncode != 0:
        return {}
    snap: dict[int, tuple[int, str]] = {}
    for line in r.stdout.decode("utf-8", errors="replace").splitlines():
        fields = line.split(None, 2)
        if len(fields) != 3:
            continue
        try:
            pid, ppid = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        snap[pid] = (ppid, os.path.basename(fields[2].strip()))
    return snap


def _has_live_claude_ancestor(
    pid: int, snap: dict[int, tuple[int, str]], max_depth: int = 25
) -> bool:
    """Walk the parent chain; True iff any ancestor (or the process itself)
    is a live `claude` process. Zombie MCPs whose session died get
    re-parented toward PID 1, so the walk reaches init without ever seeing
    `claude`."""
    cur = pid
    seen: set[int] = set()
    for _ in range(max_depth):
        ent = snap.get(cur)
        if ent is None:
            return False
        ppid, comm = ent
        if comm == "claude":
            return True
        if cur in seen or ppid <= 1 or ppid == cur:
            return False
        seen.add(cur)
        cur = ppid
    return False


def _list_processes_posix(pattern: str) -> list[dict]:
    """macOS/Linux: ps -xo (own-user processes, no terminal requirement),
    command-line filtered in Python. Returns [] on any failure — never
    raises. Ages come from etime, converted to a synthetic CreationDate so
    _classify_stale stays shared with the Windows path. Each row also
    carries `ancestor_live_claude` so the classifier can distinguish a
    concurrent live session's MCP (old but parented to a running `claude`)
    from a true orphan."""
    try:
        r = subprocess.run(
            ["ps", "-xo", "pid=,etime=,command="],
            capture_output=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []
    if r.returncode != 0:
        return []
    snap = _process_snapshot()
    now = datetime.now(timezone.utc)
    out_rows = []
    for line in r.stdout.decode("utf-8", errors="replace").splitlines():
        fields = line.split(None, 2)
        if len(fields) != 3:
            continue
        pid_s, etime, command = fields
        if pattern not in command:
            continue
        try:
            pid = int(pid_s)
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        age = _parse_etime_seconds(etime)
        if age is None:
            continue
        created = (now - timedelta(seconds=age)).isoformat()
        row = {"pid": pid, "created": created}
        if snap:
            row["ancestor_live_claude"] = _has_live_claude_ancestor(pid, snap)
        out_rows.append(row)
    return out_rows


def _list_processes_by_pattern(pattern: str) -> list[dict]:
    """Return [{pid, created(ISO)}, ...] for processes matching pattern."""
    if sys.platform == "win32":
        return _list_processes_win(pattern)
    return _list_processes_posix(pattern)


def _kill_pid_win(pid: int) -> bool:
    """taskkill /F /PID. Returns True on success."""
    try:
        env = os.environ.copy()
        env["MSYS_NO_PATHCONV"] = "1"
        r = subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)],
            capture_output=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
            startupinfo=_startupinfo(),
            env=env,
        )
        return r.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _kill_pid_posix(pid: int) -> bool:
    """SIGTERM, brief grace, escalate to SIGKILL. Returns True once the
    process is gone (or was already gone)."""
    if pid <= 1:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return True  # already gone
    except (PermissionError, OSError):
        return False  # not ours to kill
    time.sleep(0.2)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True  # exited on SIGTERM
    except (PermissionError, OSError):
        return False
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    except (PermissionError, OSError):
        return False
    return True


def _kill_pid(pid: int) -> bool:
    if sys.platform == "win32":
        return _kill_pid_win(pid)
    return _kill_pid_posix(pid)


def _classify_stale(rows: list[dict], now: datetime) -> tuple[list[int], list[int]]:
    """Split rows into (current_pids, stale_pids).

    A process is current if its CreationDate is within STALE_THRESHOLD_SECS
    of `now` (just spawned by this session), OR — when the row carries
    ancestry evidence (`ancestor_live_claude`, POSIX only) — if it is
    parented to a live `claude` process (a concurrent session's MCP).
    Only old AND orphaned processes are stale. Rows without the ancestry
    key (Windows) keep the legacy age-only classification.
    """
    current: list[int] = []
    stale: list[int] = []
    for row in rows:
        try:
            created = datetime.fromisoformat(row["created"].replace("Z", "+00:00"))
        except (ValueError, KeyError):
            continue
        age = (now - created).total_seconds()
        if age <= STALE_THRESHOLD_SECS:
            current.append(row["pid"])
        elif row.get("ancestor_live_claude") is True:
            current.append(row["pid"])
        else:
            stale.append(row["pid"])
    return current, stale


def cleanup_stale_mcps() -> list[str]:
    """Identify and kill stale MCP processes. Return warning messages.

    Empty list = no stale processes found (steady state). Non-empty =
    one or more processes were killed.
    """
    now = datetime.now(timezone.utc)
    summary: list[str] = []
    diag = {"timestamp": now.isoformat(), "groups": []}

    for label, pattern in _mcp_patterns():
        rows = _list_processes_by_pattern(pattern)
        if not rows:
            continue
        current, stale = _classify_stale(rows, now)
        group_diag = {
            "label": label,
            "pattern": pattern,
            "total": len(rows),
            "current": current,
            "stale": stale,
            "killed": [],
        }
        for pid in stale:
            if _kill_pid(pid):
                group_diag["killed"].append(pid)
        if group_diag["killed"]:
            # Current-session PIDs are debug detail — they live in
            # LAST_RUN_MARKER, not the user-facing banner (2026-07-05
            # banner-noise pass).
            summary.append(
                f"MCP-ZOMBIE: killed {len(group_diag['killed'])} stale "
                f"{label} process(es) (PIDs: {group_diag['killed']})."
            )
        diag["groups"].append(group_diag)

    # Persist diagnostics for debugging — overwritten each run.
    try:
        LAST_RUN_MARKER.parent.mkdir(parents=True, exist_ok=True)
        LAST_RUN_MARKER.write_text(json.dumps(diag, indent=2), encoding="utf-8")
    except OSError:
        pass

    return summary
