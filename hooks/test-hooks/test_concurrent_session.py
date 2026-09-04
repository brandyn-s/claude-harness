"""Tests for session_start_modules/concurrent_session.py (liveness-based).

The 2026-06-11 incident this module's design addresses: presence-based
markers + Stop-event removal leaked 37 dead markers inside the 24h prune
window, wedging repo_sync's auto-checkpoint permanently. These tests pin
the liveness semantics: a marker counts only while its session_pid is
alive and plausibly the writer's process.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS_DIR))

from session_start_modules import concurrent_session as cs  # noqa: E402 -- resolves via the sys.path insert above

POSIX = os.name == "posix"


@pytest.fixture
def marker_dir(tmp_path, monkeypatch):
    d = tmp_path / "markers"
    monkeypatch.setattr(cs, "MARKER_DIR", d)
    return d


def _write_marker(marker_dir, session_id, **fields):
    marker_dir.mkdir(parents=True, exist_ok=True)
    data = {"session_id": session_id, "pid": 12345, "started_at": time.time()}
    data.update(fields)
    (marker_dir / f"{session_id}.json").write_text(
        json.dumps(data), encoding="utf-8"
    )
    return data


def _dead_pid():
    """A pid guaranteed dead: spawn a no-op child and reap it."""
    proc = subprocess.Popen(
        [sys.executable, "-c", "pass"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    proc.wait()
    return proc.pid


# ── marker writing ──────────────────────────────────────────────────────


def test_write_marker_includes_session_pid_field(marker_dir):
    cs.write_session_marker("sess-a")
    data = json.loads((marker_dir / "sess-a.json").read_text(encoding="utf-8"))
    assert "session_pid" in data
    # On platforms without ps the walk degrades to None; where it works,
    # the recorded pid must be a live process.
    spid = data["session_pid"]
    assert spid is None or (isinstance(spid, int) and cs._pid_alive(spid))


@pytest.mark.skipif(not POSIX, reason="ancestry walk requires ps")
def test_find_session_pid_returns_live_nonshell_ancestor():
    """When the walk SUCCEEDS its result must be a live non-shell pid.

    None is a documented, legitimate outcome -- find_session_pid()'s own docstring
    says so ("A None degrades the marker to not-live -- detection disables rather
    than producing false positives"), and it is returned on pid<=1, an unreadable
    `comm`, OR exhausting _ANCESTRY_MAX_HOPS (8). Under pytest the ancestry is
    deeper than a real hook invocation (pytest -> runner -> shell -> ...), so 8
    hops is marginal and a transient `ps` failure lands on the same branch.

    Asserting `isinstance(spid, int)` unconditionally therefore asserted a
    property the function does not guarantee, and it failed INTERMITTENTLY: the
    same committed tree ran green / 1-failed / green across three full-suite runs
    (2026-07-31), while passing 20/20 in isolation every time. The sibling test
    above already had this right (`spid is None or (...)`); this one was the
    outlier.

    Kept as a CONDITIONAL assertion rather than deleted: the success path is the
    one that matters, and it is still fully checked whenever the walk resolves.
    """
    spid = cs.find_session_pid()
    if spid is None:
        pytest.skip("ancestry walk degraded to None (documented path: pid<=1, "
                    "unreadable comm, or >8 hops) — nothing to assert about")
    assert isinstance(spid, int) and spid > 1
    assert cs._pid_alive(spid)
    comm = cs._comm_basename(spid)
    assert comm is not None and comm not in cs._SHELL_COMMS


def test_walk_skips_shells_and_stops_at_the_first_real_ancestor(monkeypatch):
    """The walk's LOGIC, on a PINNED ancestry — the live test cannot assert this.

    Why both tests exist: the live one above reads real process ancestry, which is
    unpinnable and changes between probes. Measured 2026-07-31 while
    mutation-testing it: the parent `zsh` (pid 64434) was readable on one probe and
    already EXITED on the next, in the same session. So a mutation of the
    shell-skipping branch produced an unstable verdict — it MISSED, not because the
    assertion was weak and not because the mutation was inert, but because its
    observable effect depended on external state that moved underneath it.

    A mutation whose effect depends on live state cannot yield a stable verdict.
    The fix is to PIN the state rather than mutate the reader — which is also why
    the live test above had to become conditional.

    Chain: self -> sh -> zsh -> claude. The walk must skip BOTH shells and return
    the `claude` pid, not the first ancestor.
    """
    # TWO maps, deliberately: find_session_pid() calls _comm_basename(PPID), so a
    # single (parent, comm) tuple per pid conflates "this pid's parent" with "this
    # pid's own name" and is off by one. The first version of this fixture did
    # exactly that and returned 12 instead of 13 — the FIXTURE was wrong, not the
    # walk (tdd-quality item 18: a surprising result indicts the fixture first).
    parent = {10: 11, 11: 12, 12: 13}
    comm = {10: "python", 11: "sh", 12: "zsh", 13: "claude"}
    monkeypatch.setattr(cs.os, "getpid", lambda: 10)
    monkeypatch.setattr(cs, "_ppid_of", lambda p: parent.get(p))
    monkeypatch.setattr(cs, "_comm_basename", lambda p: comm.get(p))

    assert cs.find_session_pid() == 13, "walk must skip shells, not stop at the first"


def test_walk_returns_None_when_the_hop_budget_is_exhausted(monkeypatch):
    """All shells, forever — the documented None path, asserted deterministically.

    This is the branch the live test kept landing on intermittently. Pinned, it is
    a real assertion instead of a skip.
    """
    monkeypatch.setattr(cs.os, "getpid", lambda: 100)
    monkeypatch.setattr(cs, "_ppid_of", lambda p: p + 1)
    monkeypatch.setattr(cs, "_comm_basename", lambda p: "zsh")

    assert cs.find_session_pid() is None, (
        f"an all-shell ancestry must exhaust _ANCESTRY_MAX_HOPS "
        f"({cs._ANCESTRY_MAX_HOPS}) and degrade to None")


# ── liveness classification ─────────────────────────────────────────────


def test_live_marker_counts_as_concurrent(marker_dir):
    _write_marker(marker_dir, "other", session_pid=os.getpid())
    assert cs.has_concurrent_sessions("me") is True


def test_dead_pid_marker_not_concurrent(marker_dir):
    _write_marker(marker_dir, "other", session_pid=_dead_pid())
    assert cs.has_concurrent_sessions("me") is False


def test_legacy_marker_without_session_pid_not_concurrent(marker_dir):
    # Pre-liveness format: only the hook's pid, dead within seconds of
    # writing. Must never count, even when fresh.
    _write_marker(marker_dir, "other")
    assert cs.has_concurrent_sessions("me") is False


def test_self_marker_excluded(marker_dir):
    _write_marker(marker_dir, "me", session_pid=os.getpid())
    assert cs.has_concurrent_sessions("me") is False


def test_clear_residue_same_session_pid_not_concurrent(marker_dir):
    # /clear re-keys the session_id without restarting the process: the
    # old marker carries OUR session_pid and must not count as another
    # session.
    _write_marker(marker_dir, "me", session_pid=os.getpid())
    _write_marker(marker_dir, "pre-clear", session_pid=os.getpid())
    assert cs.has_concurrent_sessions("me") is False


@pytest.mark.skipif(not POSIX, reason="start-time check requires ps etime")
def test_recycled_pid_marker_not_live(marker_dir):
    # Marker claims it was written 30 days ago by this pid, but the
    # current process holding the pid started recently -> recycled.
    data = _write_marker(
        marker_dir,
        "other",
        session_pid=os.getpid(),
        started_at=time.time() - 30 * 86400,
    )
    assert cs._marker_is_live(data) is False
    assert cs.has_concurrent_sessions("me") is False


def test_distinct_live_process_detected_then_cleared(marker_dir):
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _write_marker(marker_dir, "other", session_pid=proc.pid)
        assert cs.has_concurrent_sessions("me") is True
    finally:
        proc.kill()
        proc.wait()
    assert cs.has_concurrent_sessions("me") is False


# ── pruning ─────────────────────────────────────────────────────────────


def test_prune_removes_dead_legacy_and_malformed_keeps_live(marker_dir):
    _write_marker(marker_dir, "dead", session_pid=_dead_pid())
    _write_marker(marker_dir, "legacy")  # no session_pid
    _write_marker(marker_dir, "live", session_pid=os.getpid())
    (marker_dir / "malformed.json").write_text("not json{", encoding="utf-8")

    cs.prune_stale_markers()

    remaining = sorted(p.name for p in marker_dir.glob("*.json"))
    assert remaining == ["live.json"]


def test_prune_handles_missing_dir(tmp_path, monkeypatch):
    # MARKER_DIR may not exist on first run; must not raise. Monkeypatched
    # to a nonexistent path — never the real ~/.claude/.session-active
    # (first version of this test pruned the live dir; harmless here but
    # exactly the hook-git-state-safety "test harness touches live state"
    # class).
    monkeypatch.setattr(cs, "MARKER_DIR", tmp_path / "nonexistent")
    cs.prune_stale_markers()


def test_remove_session_marker_still_works(marker_dir):
    _write_marker(marker_dir, "gone", session_pid=os.getpid())
    cs.remove_session_marker("gone")
    assert not (marker_dir / "gone.json").exists()


# ── etime parsing ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("33", 33),
        ("05:33", 333),
        ("1:02:03", 3723),
        ("3-01:02:03", 3 * 86400 + 3723),
        ("  00:09 ", 9),
        ("garbage", None),
        ("", None),
        ("1:2:3:4", None),
    ],
)
def test_parse_etime(raw, expected):
    assert cs._parse_etime(raw) == expected
