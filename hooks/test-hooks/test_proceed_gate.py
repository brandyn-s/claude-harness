#!/usr/bin/env python3
"""Tests for hooks/proceed-gate.py.

Offline. Runs the hook as a SUBPROCESS with an isolated HOME because the hook
resolves its state directory from Path.home() at import time, and with the
session ledger importable from the hooks directory so the ingest path is real.

Load-bearing properties:
  - exit 0 on every path (UserPromptSubmit exit 2 erases the prompt)
  - bare continuations get the restatement contract; real prompts do not
  - the /frame nudge fires once per session and never for questions
  - INTENT.md bullets land in the session ledger exactly once per content hash
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "proceed-gate.py"
SID = "sess-gate-001"


class ProceedGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.cwd = Path(self.tmp.name) / "repo"
        self.cwd.mkdir()

    def run_hook(self, prompt, cwd=None, sid=SID, event="UserPromptSubmit"):
        env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home))
        env.pop("CLAUDE_SESSION_ID", None)
        payload = {"hook_event_name": event, "session_id": sid,
                   "prompt": prompt, "cwd": str(cwd or self.cwd)}
        return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                              capture_output=True, text=True, env=env, timeout=60)

    # -- exit code -----------------------------------------------------------
    def test_garbage_stdin_exits_zero(self):
        env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home))
        res = subprocess.run([sys.executable, str(HOOK)], input="not json",
                             capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(res.returncode, 0)

    def test_other_event_is_ignored(self):
        res = self.run_hook("proceed", event="PostCompact")
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout.strip(), "")

    # -- continuation detection ---------------------------------------------
    def test_bare_continuations_get_the_contract(self):
        for p in ("proceed", "Continue", "ok go ahead", "Do it all", "fix 1, 2 and 4",
                  "1,2,3", "yes, continue.", "implement all", "do #2 and #5", "next"):
            res = self.run_hook(p, sid=f"{SID}-{abs(hash(p))}")
            self.assertEqual(res.returncode, 0, p)
            self.assertIn("<proceed-gate>", res.stdout, p)
            self.assertIn("DO ", res.stdout, p)

    def test_real_prompts_do_not_get_the_contract(self):
        for p in ("Continue the migration but keep the old table until Friday",
                  "Proceed with option B and skip the cache layer",
                  "/frame build the importer",
                  "why did the last run fail?"):
            res = self.run_hook(p, sid=f"{SID}-{abs(hash(p))}")
            self.assertEqual(res.returncode, 0, p)
            self.assertNotIn("This prompt is a bare continuation", res.stdout, p)

    # -- frame nudge ----------------------------------------------------------
    def test_frame_nudge_once_per_session_for_substantive_ask(self):
        first = self.run_hook("Build the CSV importer with validation and a CLI")
        self.assertIn("<frame-nudge>", first.stdout)
        second = self.run_hook("Add a --dry-run flag to the importer")
        self.assertNotIn("<frame-nudge>", second.stdout)

    def test_no_frame_nudge_for_questions_or_meta(self):
        for p in ("What does the importer do?", "help me understand the hook routing",
                  "explain how compaction works here"):
            res = self.run_hook(p, sid=f"{SID}-{abs(hash(p))}")
            self.assertNotIn("<frame-nudge>", res.stdout, p)

    def test_no_frame_nudge_when_intent_exists(self):
        (self.cwd / "INTENT.md").write_text("# Intent\n", encoding="utf-8")
        res = self.run_hook("Build the CSV importer with validation and a CLI")
        self.assertNotIn("<frame-nudge>", res.stdout)

    # -- ledger ingest --------------------------------------------------------
    def _write_intent(self, extra=""):
        (self.cwd / "INTENT.md").write_text(
            "# Intent\n\n## Problem\nImports are manual.\n\n"
            "## Done when\n- [ ] `make check` passes\n- [ ] 10k-row file imports under 5 s\n\n"
            "## Non-goals\n- No UI this week\n\n"
            "## Constraints\n- Python 3.12 only\n" + extra, encoding="utf-8")

    def _ledger(self):
        p = self.home / ".claude" / "session-ledgers" / f"{SID}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def test_intent_is_ingested_once_and_kinds_are_mapped(self):
        if not (HOOK.parent / "session_ledger.py").is_file():
            self.skipTest("session_ledger.py not beside the hook")
        self._write_intent()
        res = self.run_hook("proceed")
        self.assertEqual(res.returncode, 0)
        self.assertIn("INTENT.md item(s) recorded", res.stdout)
        ledger = self._ledger()
        self.assertIsNotNone(ledger)
        kinds = sorted(e["kind"] for e in ledger["entries"])
        self.assertEqual(kinds, ["constraint", "deliverable", "deliverable", "rejected"])
        self.assertTrue(all(e["source"] == "INTENT.md" for e in ledger["entries"]))
        # Same content again -> no re-ingest, no receipt.
        again = self.run_hook("continue")
        self.assertNotIn("recorded", again.stdout)
        self.assertEqual(len(self._ledger()["entries"]), 4)
        # Changed content -> new bullets are added, old ones de-duplicated.
        self._write_intent(extra="- No network calls in tests\n")
        third = self.run_hook("go ahead")
        self.assertIn("1 INTENT.md item(s) recorded", third.stdout)
        self.assertEqual(len(self._ledger()["entries"]), 5)


if __name__ == "__main__":
    unittest.main()
