#!/usr/bin/env python3
"""Tests for hooks/compaction-budget.py.

Offline. Subprocess with an isolated HOME (state dir resolves from Path.home()).

Load-bearing properties:
  - PostCompact says nothing (it cannot inject) and exits 0
  - below the threshold, prompts get nothing
  - at the threshold the nudge fires exactly once per compaction count
  - a session ledger, when present, gets its compaction_count written
  - PostCompact audits the compact summary against the ledger and appends the row
    to ~/.claude/audit/ledger-audit-YYYYMMDD.jsonl; a dropped REJECTED entry is
    named once on the next prompt
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "compaction-budget.py"
SID = "sess-budget-001"


class CompactionBudget(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()

    def run_hook(self, payload, threshold=None):
        env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home))
        env.pop("CLAUDE_COMPACTION_BUDGET", None)
        if threshold is not None:
            env["CLAUDE_COMPACTION_BUDGET"] = str(threshold)
        return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=60)

    def compact(self, trigger="auto"):
        return self.run_hook({"hook_event_name": "PostCompact", "session_id": SID,
                              "trigger": trigger, "compact_summary": "s"})

    def prompt(self, threshold=None):
        return self.run_hook({"hook_event_name": "UserPromptSubmit", "session_id": SID,
                              "prompt": "next"}, threshold=threshold)

    def state(self):
        p = self.home / ".claude" / "run" / "compaction-budget" / f"{SID}.json"
        return json.loads(p.read_text(encoding="utf-8"))

    def test_post_compact_counts_and_says_nothing(self):
        res = self.compact()
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), "")
        self.assertEqual(self.state()["count"], 1)

    def test_below_threshold_is_silent(self):
        self.compact()
        res = self.prompt()
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), "")

    def test_nudge_fires_once_per_count_at_threshold(self):
        self.compact()
        self.compact()
        first = self.prompt()
        self.assertIn("<compaction-budget>", first.stdout)
        self.assertIn("compacted 2 time", first.stdout)
        self.assertIn("HANDOFF.md", first.stdout)
        second = self.prompt()
        self.assertEqual(second.stdout.strip(), "", "must not repeat for the same count")
        self.compact()
        third = self.prompt()
        self.assertIn("compacted 3 time", third.stdout)

    def test_threshold_env_override(self):
        self.compact()
        res = self.prompt(threshold=1)
        self.assertIn("<compaction-budget>", res.stdout)

    def test_ledger_compaction_count_is_written_when_ledger_exists(self):
        if not (HOOK.parent / "session_ledger.py").is_file():
            self.skipTest("session_ledger.py not beside the hook")
        ldir = self.home / ".claude" / "session-ledgers"
        ldir.mkdir(parents=True)
        (ldir / f"{SID}.json").write_text(json.dumps({
            "schema": "session-ledger/1", "session_id": SID, "cwd": "", "created_ts": 0,
            "updated_ts": 0, "compaction_count": 0, "entries": []}), encoding="utf-8")
        self.compact()
        self.compact()
        ledger = json.loads((ldir / f"{SID}.json").read_text(encoding="utf-8"))
        self.assertEqual(ledger["compaction_count"], 2)

    def _write_ledger(self, entries):
        ldir = self.home / ".claude" / "session-ledgers"
        ldir.mkdir(parents=True, exist_ok=True)
        (ldir / f"{SID}.json").write_text(json.dumps({
            "schema": "session-ledger/1", "session_id": SID, "cwd": "", "created_ts": 0,
            "updated_ts": 0, "compaction_count": 0,
            "entries": [{"kind": k, "text": t, "source": "", "added_ts": 0, "restated": 0, "satisfied": None}
                        for k, t in entries]}), encoding="utf-8")

    def test_post_compact_audits_the_summary_and_appends_a_row(self):
        self._write_ledger([("rejected", "Do not add a Stop hook phrase blocker"),
                            ("deliverable", "Produce the handoff document")])
        res = self.run_hook({"hook_event_name": "PostCompact", "session_id": SID, "trigger": "auto",
                             "compact_summary": "We produced the handoff document."})
        self.assertEqual(res.returncode, 0)
        rows = sorted((self.home / ".claude" / "audit").glob("ledger-audit-*.jsonl"))
        self.assertEqual(len(rows), 1)
        row = json.loads(rows[0].read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(row["session_id"], SID)
        self.assertEqual(row["total_entries"], 2)
        self.assertEqual(row["rejected_dropped_count"], 1)
        self.assertEqual(row["not_found"][0]["kind"], "rejected")
        self.assertEqual(self.state()["last_audit"]["rejected_dropped"],
                         ["Do not add a Stop hook phrase blocker"])

    def test_dropped_rejection_is_named_once_on_the_next_prompt(self):
        self._write_ledger([("rejected", "Do not add a Stop hook phrase blocker")])
        self.run_hook({"hook_event_name": "PostCompact", "session_id": SID, "trigger": "auto",
                       "compact_summary": "unrelated summary text"})
        first = self.prompt()
        self.assertIn("<ledger-audit>", first.stdout)
        self.assertIn("Do not add a Stop hook phrase blocker", first.stdout)
        self.assertNotIn("<compaction-budget>", first.stdout, "one compaction is below the handoff threshold")
        second = self.prompt()
        self.assertEqual(second.stdout.strip(), "", "the audit note is shown once")

    def test_summary_that_covers_the_ledger_produces_no_note(self):
        self._write_ledger([("rejected", "Do not add a Stop hook phrase blocker")])
        self.run_hook({"hook_event_name": "PostCompact", "session_id": SID, "trigger": "auto",
                       "compact_summary": "The user rejected adding a Stop hook phrase blocker; nothing else."})
        self.assertEqual(self.prompt().stdout.strip(), "")
        rows = sorted((self.home / ".claude" / "audit").glob("ledger-audit-*.jsonl"))
        self.assertEqual(len(rows), 1, "the row is written even when nothing was dropped")

    def test_garbage_stdin_exits_zero(self):
        env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home))
        res = subprocess.run([sys.executable, str(HOOK)], input="{", capture_output=True,
                             text=True, env=env, timeout=60)
        self.assertEqual(res.returncode, 0)


if __name__ == "__main__":
    unittest.main()
