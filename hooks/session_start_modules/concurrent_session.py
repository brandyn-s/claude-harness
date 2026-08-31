"""Concurrent session detection (liveness-based).

Each Claude Code session writes a marker file at session-start recording
the SESSION PROCESS pid (found by walking the hook's ancestry past shell
wrappers). repo_sync treats a marker as a concurrent session only while
that pid is still alive — preventing one session's session-start hook
from silently abandoning another LIVE session's working-tree edits onto
a checkpoint branch, without dead sessions' markers wedging the sync.

Marker location: ~/.claude/.session-active/{session_id}.json
Marker shape:    {session_id, pid, session_pid, started_at}
  pid         — the hook process (debug/attribution only; dies in seconds)
  session_pid — the long-lived Claude session process; the liveness key

Failure modes this design addresses:

2026-04-26 incident (why markers exist at all):
  Session A edits rules/git-hygiene.md; session B launches and runs
  repo_sync, which checkpoints A's uncommitted edits onto a branch and
  checks back to main. From A's POV the working tree silently reverted.

2026-06-11 incident (why liveness replaced presence + the 24h prune):
  The original design removed markers on the Stop hook (fires at the end
  of EVERY turn, so live sessions lost their marker after turn 1) and
  pruned leaks on a 24h age cutoff. Sessions ending without a clean
  final Stop — closed terminal, crash, /clear re-keying the session_id —
  leaked markers faster than the cutoff cleared them: 37 dead markers
  accumulated inside the window, so has_concurrent_sessions() was
  effectively always True, repo_sync permanently skipped, and stranded
  dirty files re-warned at every session start. The recorded pid was
  also the HOOK's (os.getpid()), dead within seconds, so liveness
  checking was impossible without re-keying the marker to the session
  process. Markers now persist for the session's lifetime and are
  pruned the moment their session_pid dies.

Platform note: the ancestry walk and start-time check shell out to
`ps -p <pid> -o <field>=` (specific-PID, single-field — never a wide
listing; see platform-constraints wide-process-listing rule). Where ps
is unavailable (Windows), find_session_pid() returns None and the
marker degrades to not-live: detection disables rather than wedging the
sync, matching this deployment's macOS-only posture.
"""

import json
import os
import subprocess
import time
from pathlib import Path

MARKER_DIR = Path.home() / ".claude" / ".session-active"

# Shell wrappers that may sit between the hook process and the Claude
# session process. Verified chain on this host (2026-06-11):
#   python3 (hook) -> bash (run-hook keeps a telemetry wrapper alive; it
#   does NOT exec) -> [/bin/sh -c usually execs away] -> claude -> -zsh
# The first non-shell ancestor is the session process; the walk stops
# there, well before the long-lived terminal shell.
_SHELL_COMMS = {"bash", "sh", "zsh", "dash", "fish", "ksh", "tcsh", "csh"}
_ANCESTRY_MAX_HOPS = 8

# A marker's session_pid must belong to a process that started BEFORE
# the marker was written (small slack for clock fuzz). A recycled pid —
# an unrelated process that grabbed the number after the session died —
# starts later and is rejected, so it can't wedge the sync forever.
_PID_START_SLACK_SECS = 120


def _ensure_dir() -> None:
    MARKER_DIR.mkdir(parents=True, exist_ok=True)


def _marker_path(session_id: str) -> Path:
    # Use only safe filename chars from session_id
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
    return MARKER_DIR / f"{safe}.json"


def _ps_field(pid: int, fmt: str) -> str | None:
    """One ps output field for one specific pid; None on any failure."""
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", f"{fmt}="],
            capture_output=True,
            timeout=5,
        )
        if out.returncode != 0:
            return None
        val = out.stdout.decode("utf-8", errors="replace").strip()
        return val or None
    except Exception:
        return None


def _ppid_of(pid: int) -> int | None:
    val = _ps_field(pid, "ppid")
    try:
        return int(val) if val else None
    except ValueError:
        return None


def _comm_basename(pid: int) -> str | None:
    """Normalized executable name: basename, login-shell dash stripped."""
    comm = _ps_field(pid, "comm")
    if not comm:
        return None
    return os.path.basename(comm).lstrip("-").lower()


def find_session_pid() -> int | None:
    """Walk this hook's ancestry to the Claude session process.

    Returns the first non-shell ancestor's pid, or None when the walk
    fails (no ps, reached pid 1). A None degrades the marker to
    not-live — detection disables rather than producing false
    positives.
    """
    pid = os.getpid()
    for _ in range(_ANCESTRY_MAX_HOPS):
        ppid = _ppid_of(pid)
        if not ppid or ppid <= 1:
            return None
        comm = _comm_basename(ppid)
        if comm is None:
            return None
        if comm not in _SHELL_COMMS:
            return ppid
        pid = ppid
    return None


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else
    except Exception:
        return False


def _pid_alive_windows(pid: int) -> bool:
    """Honest liveness on Windows.

    os.kill(pid, 0) reports terminated-but-handle-held processes as
    alive: OpenProcess succeeds while ANY handle to the process object
    remains (e.g. a subprocess.Popen that hasn't been GC'd — caught by
    CI's windows-2022 leg on this module's own test suite).
    GetExitCodeProcess == STILL_ACTIVE distinguishes actually-running.
    """
    try:
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, 0, pid
        )
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return False


def _parse_etime(s: str) -> int | None:
    """ps etime ([[dd-]hh:]mm:ss) -> elapsed seconds; None on bad input."""
    try:
        s = s.strip()
        days = 0
        if "-" in s:
            d, s = s.split("-", 1)
            days = int(d)
        parts = [int(p) for p in s.split(":")]
        if not parts or len(parts) > 3:
            return None
        while len(parts) < 3:
            parts.insert(0, 0)
        h, m, sec = parts
        return ((days * 24 + h) * 3600) + m * 60 + sec
    except Exception:
        return None


def _proc_start_epoch(pid: int) -> float | None:
    et = _ps_field(pid, "etime")
    secs = _parse_etime(et) if et else None
    return time.time() - secs if secs is not None else None


def _marker_is_live(data: dict) -> bool:
    """A marker is live iff its session_pid is alive and plausibly the
    same process that wrote the marker (start-time predates the marker).

    Markers without a session_pid — the pre-liveness format, whose pid
    field was the hook process and dead within seconds — are never live.
    """
    spid = data.get("session_pid")
    if not isinstance(spid, int) or spid <= 1:
        return False
    if not _pid_alive(spid):
        return False
    start = _proc_start_epoch(spid)
    started_at = data.get("started_at", 0)
    if start is not None and start > started_at + _PID_START_SLACK_SECS:
        return False  # pid recycled by an unrelated newer process
    return True


def write_session_marker(session_id: str | None) -> None:
    """Write marker for the current session at session-start."""
    if not session_id:
        return
    _ensure_dir()
    marker = _marker_path(session_id)
    try:
        marker.write_text(
            json.dumps(
                {
                    "session_id": session_id,
                    "pid": os.getpid(),
                    "session_pid": find_session_pid(),
                    "started_at": time.time(),
                }
            ),
            encoding="utf-8",
        )
    except Exception:
        pass  # never block session-start


def remove_session_marker(session_id: str | None) -> None:
    """Remove a session's marker.

    No longer called from the Stop hook (Stop fires at the end of every
    turn, which disarmed protection for live multi-turn sessions — see
    module docstring). Liveness pruning at session-start is the cleanup
    path; this remains for tests and manual repair.
    """
    if not session_id:
        return
    try:
        _marker_path(session_id).unlink(missing_ok=True)
    except Exception:
        pass


def prune_stale_markers() -> None:
    """Remove markers whose session process is gone.

    Covers dead sessions, pre-liveness legacy markers (hook pids, dead
    by construction), recycled pids, and malformed files. Runs at every
    session-start, immediately after write_session_marker — the fresh
    self marker is live, so it survives.
    """
    if not MARKER_DIR.is_dir():
        return
    for marker in MARKER_DIR.glob("*.json"):
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            if not _marker_is_live(data):
                marker.unlink(missing_ok=True)
        except Exception:
            # Malformed marker: treat as stale
            try:
                marker.unlink(missing_ok=True)
            except Exception:
                pass


def has_concurrent_sessions(self_session_id: str | None) -> bool:
    """Return True if another LIVE session's marker exists.

    Live = session_pid alive + start-time sanity (see _marker_is_live).
    Markers sharing this session's own session_pid are residue of the
    same process (/clear re-keys the session_id without restarting the
    process) and do not count.
    """
    if not MARKER_DIR.is_dir():
        return False

    self_spid = None
    if self_session_id:
        try:
            data = json.loads(
                _marker_path(self_session_id).read_text(encoding="utf-8")
            )
            spid = data.get("session_pid")
            self_spid = spid if isinstance(spid, int) else None
        except Exception:
            self_spid = None

    for marker in MARKER_DIR.glob("*.json"):
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except Exception:
            continue  # prune_stale_markers handles deletion
        if data.get("session_id") == self_session_id:
            continue
        if self_spid is not None and data.get("session_pid") == self_spid:
            continue  # same process: marker re-keyed by /clear or resume
        if _marker_is_live(data):
            return True
    return False
