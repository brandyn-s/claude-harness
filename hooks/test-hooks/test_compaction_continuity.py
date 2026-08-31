#!/usr/bin/env python3
"""Tests for hooks/compaction-continuity.py.

Offline. Run as a SUBPROCESS with an isolated HOME because the hook resolves its
marker directory from Path.home() at import time. HOME and USERPROFILE are both
set so isolation holds on Windows.

The load-bearing property is FIRE-ONCE: a reminder that repeats on every prompt
becomes noise and gets ignored, which is the same outcome as not having it.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "compaction-continuity.py"
SID = "sess-abc-123"


class ContinuityMarker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()

    def run_hook(self, payload):
        env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home))
        return subprocess.run([sys.executable, str(HOOK)],
                              input=json.dumps(payload), capture_output=True,
                              text=True, env=env, timeout=60)

    def markers(self):
        d = self.home / ".claude" / "run" / "compaction"
        return sorted(p.name for p in d.glob("*.json")) if d.is_dir() else []

    def compact(self, trigger="auto"):
        return self.run_hook({"hook_event_name": "PostCompact",
                              "session_id": SID, "trigger": trigger,
                              "compact_summary": "a summary"})

    def prompt(self):
        return self.run_hook({"hook_event_name": "UserPromptSubmit",
                              "session_id": SID, "prompt": "next thing"})

    def test_post_compact_writes_a_marker_and_says_nothing(self):
        res = self.compact()
        self.assertEqual(res.returncode, 0)
        self.assertEqual(self.markers(), [f"{SID}.json"])
        # PostCompact cannot inject context; it must not try.
        self.assertEqual(res.stdout.strip(), "")

    def test_prompt_after_compaction_injects_the_reminder(self):
        self.compact(trigger="auto")
        res = self.prompt()
        self.assertEqual(res.returncode, 0)
        self.assertIn("compaction-continuity", res.stdout)
        self.assertIn("re-invoke the skill", res.stdout)
        self.assertIn("auto", res.stdout, "the trigger should be named")

    def test_reminder_fires_exactly_once(self):
        """Reverting the unlink makes this fail -- the fire-once mutation."""
        self.compact()
        first = self.prompt()
        second = self.prompt()
        self.assertIn("compaction-continuity", first.stdout)
        self.assertEqual(second.stdout.strip(), "",
                         "marker must be consumed on first prompt")
        self.assertEqual(self.markers(), [], "marker must be deleted")

    def test_prompt_without_compaction_is_silent(self):
        res = self.prompt()
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), "")

    def test_marker_is_per_session(self):
        self.compact()
        other = self.run_hook({"hook_event_name": "UserPromptSubmit",
                               "session_id": "different-session",
                               "prompt": "hi"})
        self.assertEqual(other.stdout.strip(), "",
                         "another session must not consume this marker")
        self.assertEqual(self.markers(), [f"{SID}.json"])

    def test_unknown_event_is_inert(self):
        res = self.run_hook({"hook_event_name": "SessionStart",
                             "session_id": SID})
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), "")
        self.assertEqual(self.markers(), [])

    def test_malformed_stdin_never_blocks_a_prompt(self):
        """UserPromptSubmit ERASES the prompt on exit 2 -- must always be 0."""
        env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home))
        res = subprocess.run([sys.executable, str(HOOK)], input="}{not json",
                             capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(res.returncode, 0)

    def test_corrupt_marker_still_exits_zero_and_clears(self):
        d = self.home / ".claude" / "run" / "compaction"
        d.mkdir(parents=True)
        (d / f"{SID}.json").write_text("{{{ not json", encoding="utf-8")
        res = self.prompt()
        self.assertEqual(res.returncode, 0)
        self.assertEqual(self.markers(), [], "a corrupt marker must be cleared")


if __name__ == "__main__":
    unittest.main()
