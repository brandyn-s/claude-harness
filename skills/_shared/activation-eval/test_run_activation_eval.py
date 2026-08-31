#!/usr/bin/env python3
"""Tests for run_activation_eval.py — median computation + empty-data path.

Stdlib only (unittest). Run: python3 -m unittest test_run_activation_eval
or: python3 test_run_activation_eval.py
"""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import run_activation_eval as rae


class TestActivationEval(unittest.TestCase):
    def _write_jsonl(self, lines):
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, encoding="utf-8"
        )
        for obj in lines:
            tmp.write(json.dumps(obj) + "\n")
        tmp.close()
        return Path(tmp.name)

    def test_median_with_invocation_signal(self):
        # 3-line synthetic fixture, two skills.
        #   alpha: 2 hints, 1 invoked  -> activation 0.5
        #   beta:  1 hint,  1 invoked  -> activation 1.0
        # median of [0.5, 1.0] = 0.75
        fixture = [
            {"ts": "t1", "skill": "alpha", "agent": None, "matched": "a", "event": "hint"},
            {"ts": "t2", "skill": "alpha", "agent": None, "matched": "a", "invoked": True},
            {"ts": "t3", "skill": "beta", "agent": None, "matched": "b", "invoked": True},
        ]
        path = self._write_jsonl(fixture)

        events = rae.load_events(path)
        self.assertEqual(len(events), 3)
        stats = rae.compute_per_skill(events)
        self.assertAlmostEqual(stats["alpha"]["activation_rate"], 0.5)
        self.assertAlmostEqual(stats["alpha"]["false_positive_rate"], 0.5)
        self.assertAlmostEqual(stats["beta"]["activation_rate"], 1.0)

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = rae.main(["--usage-file", str(path)])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("METRIC activation_median=0.750", out)

    def test_empty_data_path(self):
        # Existing-but-empty file -> NA, no crash.
        path = self._write_jsonl([])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = rae.main(["--usage-file", str(path)])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("METRIC activation_median=NA", out)

    def test_missing_file_path(self):
        # Absent file -> clear message + NA, exit 0.
        missing = Path(tempfile.gettempdir()) / "definitely-not-here-activation.jsonl"
        if missing.exists():
            missing.unlink()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = rae.main(["--usage-file", str(missing)])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("no activation history found", out)
        self.assertIn("METRIC activation_median=NA", out)

    def test_hint_only_data_is_na(self):
        # No event/invoked field anywhere -> rates NA even with hints present.
        fixture = [
            {"ts": "t1", "skill": "alpha", "agent": None, "matched": "a"},
            {"ts": "t2", "skill": "alpha", "agent": None, "matched": "a"},
        ]
        path = self._write_jsonl(fixture)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = rae.main(["--usage-file", str(path)])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("METRIC activation_median=NA", out)


if __name__ == "__main__":
    unittest.main()
