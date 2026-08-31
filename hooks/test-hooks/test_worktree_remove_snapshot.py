#!/usr/bin/env python3
"""Tests for hooks/worktree-remove-snapshot.py.

Offline. Each test builds a real throwaway git repo and runs the hook as a
SUBPROCESS with an isolated HOME, because the hook resolves its snapshot root
from Path.home() at import time -- monkeypatching after import would not move it.
Both HOME and USERPROFILE are set so the isolation holds on Windows too.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "worktree-remove-snapshot.py"


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args],
                   capture_output=True, text=True, check=False)


def _repo(root):
    """A committed repo with one tracked file."""
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "tracked.txt").write_text("original\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-q", "-m", "init")


def _run(payload, home):
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    return subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps(payload),
        capture_output=True, text=True, env=env, timeout=60)


def _snapshots(home):
    root = home / ".claude" / "worktree-snapshots"
    return sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []


class SnapshotBehaviour(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.home = base / "home"
        self.home.mkdir()
        self.wt = base / "wt"
        self.wt.mkdir()
        _repo(self.wt)

    def test_clean_worktree_snapshots_nothing(self):
        res = _run({"hook_event_name": "WorktreeRemove",
                    "worktree_path": str(self.wt)}, self.home)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(_snapshots(self.home), [],
                         "a clean tree has nothing at risk")

    def test_modified_tracked_file_is_captured_with_its_content(self):
        (self.wt / "tracked.txt").write_text("PRECIOUS EDIT\n", encoding="utf-8")
        res = _run({"hook_event_name": "WorktreeRemove",
                    "worktree_path": str(self.wt)}, self.home)
        self.assertEqual(res.returncode, 0)
        snaps = _snapshots(self.home)
        self.assertEqual(len(snaps), 1)
        saved = snaps[0] / "tracked.txt"
        self.assertTrue(saved.is_file(), "dirty file must be copied out")
        # Content, not just existence -- an empty copy would be worthless.
        self.assertEqual(saved.read_text(encoding="utf-8"), "PRECIOUS EDIT\n")
        manifest = (snaps[0] / "MANIFEST.txt").read_text(encoding="utf-8")
        self.assertIn("tracked.txt", manifest)
        self.assertIn("head_sha", manifest)

    def test_untracked_file_is_captured(self):
        (self.wt / "new_work.md").write_text("unstaged research\n", encoding="utf-8")
        _run({"hook_event_name": "WorktreeRemove",
              "worktree_path": str(self.wt)}, self.home)
        snaps = _snapshots(self.home)
        self.assertEqual(len(snaps), 1)
        self.assertEqual((snaps[0] / "new_work.md").read_text(encoding="utf-8"),
                         "unstaged research\n")

    def test_noise_directories_are_not_copied(self):
        junk = self.wt / "node_modules" / "pkg"
        junk.mkdir(parents=True)
        (junk / "big.js").write_text("x" * 1000, encoding="utf-8")
        (self.wt / "real.txt").write_text("keep me\n", encoding="utf-8")
        _run({"hook_event_name": "WorktreeRemove",
              "worktree_path": str(self.wt)}, self.home)
        snaps = _snapshots(self.home)
        self.assertEqual(len(snaps), 1)
        self.assertTrue((snaps[0] / "real.txt").is_file())
        self.assertFalse((snaps[0] / "node_modules").exists(),
                         "node_modules must be skipped")


class NeverBreaksCleanup(unittest.TestCase):
    """The event cannot block, so the hook must be inert on every bad input."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()

    def test_missing_worktree_path_exits_zero(self):
        res = _run({"hook_event_name": "WorktreeRemove"}, self.home)
        self.assertEqual(res.returncode, 0)

    def test_nonexistent_path_exits_zero(self):
        res = _run({"hook_event_name": "WorktreeRemove",
                    "worktree_path": str(self.home / "gone")}, self.home)
        self.assertEqual(res.returncode, 0)

    def test_malformed_stdin_exits_zero(self):
        env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home))
        res = subprocess.run([sys.executable, str(HOOK)], input="not json{",
                             capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(res.returncode, 0)

    def test_non_git_directory_exits_zero_without_snapshot(self):
        plain = Path(self.tmp.name) / "plain"
        plain.mkdir()
        (plain / "f.txt").write_text("x", encoding="utf-8")
        res = _run({"hook_event_name": "WorktreeRemove",
                    "worktree_path": str(plain)}, self.home)
        self.assertEqual(res.returncode, 0)
        self.assertEqual(_snapshots(self.home), [])


if __name__ == "__main__":
    unittest.main()
