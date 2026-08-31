"""Tests for session_start_modules/worktree_gc.py — conservative worktree GC.

Safety contract:
  - live-branch worktrees are NEVER removed (would break active sessions)
  - [gone]-branch worktrees (PR merged + remote-deleted) ARE removed
  - the expensive fetch+remove pass is throttled
"""
import os
import subprocess
import sys
import time
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS))

from session_start_modules import worktree_gc as wg  # noqa: E402


def _run(cwd, *args, timeout=30):
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True, text=True, check=True, timeout=timeout,
    )


def _make_remote_and_clone(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)],
                   check=True, timeout=30)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)],
                   check=True, timeout=30)
    _run(clone, "config", "user.email", "t@example.com")
    _run(clone, "config", "user.name", "t")
    (clone / "f.txt").write_text("hi\n", encoding="utf-8")
    _run(clone, "add", "f.txt")
    _run(clone, "commit", "-q", "-m", "init")
    _run(clone, "push", "-q", "-u", "origin", "main")
    return remote, clone


def test_parse_worktrees_finds_added(tmp_path):
    _, clone = _make_remote_and_clone(tmp_path)
    wt = tmp_path / "wt-x"
    _run(clone, "worktree", "add", "-q", "-b", "feat/x", str(wt))
    parsed = {Path(p).name: b for p, b in wg._parse_worktrees(clone)}
    assert parsed.get("wt-x") == "feat/x", parsed


def test_live_branch_worktree_not_removed(tmp_path):
    _, clone = _make_remote_and_clone(tmp_path)
    wt = tmp_path / "wt-live"
    _run(clone, "worktree", "add", "-q", "-b", "feat/live", str(wt))
    _run(clone, "push", "-q", "-u", "origin", "feat/live")  # upstream stays
    wg._prune_one_repo(clone, do_expensive=True)
    assert wt.exists(), "live-branch worktree must NOT be removed"


def test_gone_branch_worktree_removed(tmp_path):
    _, clone = _make_remote_and_clone(tmp_path)
    wt = tmp_path / "wt-gone"
    _run(clone, "worktree", "add", "-q", "-b", "feat/gone", str(wt))
    _run(clone, "push", "-q", "-u", "origin", "feat/gone")
    # Simulate PR squash-merge + branch delete: drop the upstream.
    _run(clone, "push", "-q", "origin", "--delete", "feat/gone")
    # _prune_one_repo fetch --prunes -> marks feat/gone [gone] -> removes wt.
    wg._prune_one_repo(clone, do_expensive=True)
    assert not wt.exists(), "gone-branch worktree should be removed"


def test_throttle_skips_expensive_when_recent(tmp_path):
    orig = wg._STAMP
    stamp = tmp_path / "stamp"
    wg._STAMP = stamp
    try:
        stamp.write_text(str(time.time()), encoding="utf-8")
        assert wg._expensive_pass_due() is False, "fresh stamp -> not due"
        old = time.time() - wg._THROTTLE_SECS - 100
        os.utime(stamp, (old, old))
        assert wg._expensive_pass_due() is True, "stale stamp -> due"
    finally:
        wg._STAMP = orig
