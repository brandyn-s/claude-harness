#!/usr/bin/env python3
"""Tests for bin/run-status.py — the durable run-status surface.

Known-positive: full lifecycle (start -> update -> done/fail) produces the right
state + markers. Known-negative: show on a missing run errors; list on an empty
root is clean; update-before-start is forgiving.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HELPER = Path(__file__).resolve().parents[2] / "bin" / "run-status.py"


def run(args, runs_dir, stale_sec=None):
    env = dict(os.environ, CLAUDE_RUNS_DIR=str(runs_dir))
    if stale_sec is not None:
        env["CLAUDE_RUN_STALE_SEC"] = str(stale_sec)
    return subprocess.run(
        [sys.executable, str(HELPER), *args],
        capture_output=True, text=True, env=env,
    )


class RunStatusLifecycle(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.runs = Path(self._tmp.name) / "runs"

    def tearDown(self):
        self._tmp.cleanup()

    def test_start_creates_status_json(self):
        r = run(["start", "job1", "--detail", "kickoff", "--pct", "0"], self.runs)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.runs / "job1" / "status.json").exists())

    def test_update_advances_phase_and_pct(self):
        run(["start", "job1"], self.runs)
        r = run(["update", "job1", "--phase", "judging", "--pct", "47"], self.runs)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("phase=judging", r.stdout)
        self.assertIn("pct=47", r.stdout)

    def test_done_writes_marker_and_state(self):
        # 2026-07-26: `done` now REQUIRES evidence -- a .done marker is a
        # verified-success claim, not a "we stopped looping" claim. Supply an
        # attestation so this lifecycle test still exercises the success path.
        run(["start", "job1"], self.runs)
        run(["done", "job1", "--summary", "all good",
             "--verified-by", "lifecycle test"], self.runs)
        self.assertTrue((self.runs / "job1" / ".done").exists())
        self.assertEqual((self.runs / "job1" / ".done").read_text().strip(), "all good")
        r = run(["show", "job1"], self.runs)
        self.assertIn("DONE", r.stdout)

    def test_done_without_evidence_is_refused(self):
        """The verified-success gate (audit Phase 1).

        Before this gate any caller could assert success with no evidence -- the
        same summary-as-success defect the workflow journals exhibited.
        """
        run(["start", "job1"], self.runs)
        r = run(["done", "job1", "--summary", "trust me"], self.runs)
        self.assertEqual(r.returncode, 2)
        self.assertFalse((self.runs / "job1" / ".done").exists())

    def test_fail_writes_marker_and_state(self):
        run(["start", "job1"], self.runs)
        run(["fail", "job1", "--reason", "token expired"], self.runs)
        self.assertTrue((self.runs / "job1" / ".fail").exists())
        r = run(["show", "job1"], self.runs)
        self.assertIn("FAILED", r.stdout)

    def test_running_state_before_marker(self):
        run(["start", "job1"], self.runs)
        r = run(["show", "job1"], self.runs)
        self.assertIn("RUNNING", r.stdout)

    def test_stale_state_when_old(self):
        # stale_sec=0 → any age counts as stale immediately (no marker present)
        run(["start", "job1"], self.runs)
        r = run(["show", "job1"], self.runs, stale_sec=0)
        self.assertIn("STALE", r.stdout)

    def test_done_overrides_stale(self):
        # a finished run is DONE even if old — marker beats age
        # (`--verified-by` supplies the evidence the 2026-07-26 gate requires)
        run(["start", "job1"], self.runs)
        run(["done", "job1", "--verified-by", "staleness test"], self.runs)
        r = run(["show", "job1"], self.runs, stale_sec=0)
        self.assertIn("DONE", r.stdout)

    # ---- known-negative / edge cases ----
    def test_show_missing_run_errors(self):
        r = run(["show", "ghost"], self.runs)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no such run", r.stderr)

    def test_list_empty_is_clean(self):
        r = run(["list"], self.runs)
        self.assertEqual(r.returncode, 0)
        self.assertIn("no runs", r.stdout)

    def test_update_before_start_is_forgiving(self):
        # a monitor may update before an explicit start — should create, not crash
        r = run(["update", "job1", "--phase", "p2"], self.runs)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.runs / "job1" / "status.json").exists())

    def test_list_orders_and_labels(self):
        run(["start", "a"], self.runs)
        run(["start", "b"], self.runs)
        run(["fail", "a", "--reason", "x"], self.runs)
        r = run(["list"], self.runs)
        self.assertIn("FAILED", r.stdout)
        self.assertIn("RUNNING", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
