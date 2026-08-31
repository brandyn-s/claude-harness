#!/usr/bin/env python3
"""Tests for bin/workflow-run-census.py — the no-subtraction run census.

WHY THESE TESTS EXIST: the defect this tool prevents is arithmetic, and
arithmetic bugs pass every smoke test. On 2026-08-26 a workflow-health sweep
derived failures as `total - success`, which buckets healthy SKIPPED runs as
failures; it produced a false "never succeeded" finding against another team's
workflow. A test that merely asserted "BORN-BROKEN fires when there are
failures" would pass on the buggy subtraction too, so the load-bearing
fixture here is the SKIP-ONLY workflow: total=100, success=0, failure=0,
skipped=100. Under subtraction that reads as 100 failures and BORN-BROKEN;
counted honestly it is CLEAN. That one fixture is the whole point, and it is
the mutation this suite must catch.

The second class pinned here is the coverage residual. An invalid `status`
filter value returns HTTP 200 with `total_count: 0` rather than an error
(measured 2026-08-27 against brandyn-s/claude-harness: an unfiltered
total of 17,249 with `status=__nonsense__` -> 0). So a silently-wrong bucket
enum yields confident zeros, and the ONLY thing that can detect it is the
residual against the API's own unfiltered total. Its tolerance is therefore
tested from both sides.

Mechanism: the script shells out to `gh` exclusively, so a fake `gh` earlier
on PATH is a complete seam. Pure decision functions (coverage, verdict) are
tested directly — they are where the arithmetic lives.
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "bin" / "workflow-run-census.py"


def _load():
    spec = importlib.util.spec_from_file_location("census_under_test", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wrc = _load()


# A fake `gh`. Counts are keyed by the `status=` value in the query ("" for the
# unfiltered call), so a test declares a population and the fake answers every
# bucket query from it — including the buckets the test did not mention, which
# answer 0 exactly as the real API does for an absent conclusion.
FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys, urllib.parse
argv = sys.argv[1:]
with open(os.environ["FAKE_GH_LOG"], "a") as fh:
    fh.write(" ".join(argv) + "\n")
counts = json.loads(os.environ.get("FAKE_GH_COUNTS", "{}"))
workflows = os.environ.get("FAKE_GH_WORKFLOWS", "")
path = argv[1] if len(argv) > 1 else ""
jq = argv[argv.index("--jq") + 1] if "--jq" in argv else ""
if os.environ.get("FAKE_GH_FAIL_MODE") == "error_body_on_stdout":
    # Real gh writes its error JSON to STDOUT, not stderr.
    print(json.dumps({"message": "Not Found", "status": "404"}))
    sys.exit(0)
if "actions/workflows?" in path:
    print(workflows)
    sys.exit(0)
qs = urllib.parse.parse_qs(path.split("?", 1)[1] if "?" in path else "")
status = (qs.get("status") or [""])[0]
if "total_count" in jq:
    print(counts.get(status, 0))
    sys.exit(0)
if "created_at" in jq:
    page = (qs.get("page") or ["1"])[0]
    print(f"2020-01-0{min(int(page), 9)}T00:00:00Z")
    sys.exit(0)
print("")
'''


class FakeGh:
    """Context manager putting a scripted `gh` first on PATH."""

    def __init__(self, counts=None, workflows="", fail_mode=None):
        self.counts = counts or {}
        self.workflows = workflows
        self.fail_mode = fail_mode

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        gh = d / "gh"
        gh.write_text(FAKE_GH, encoding="utf-8")
        gh.chmod(0o755)
        self.log = d / "log.txt"
        self.log.write_text("", encoding="utf-8")
        self._saved = dict(os.environ)
        os.environ["PATH"] = f"{d}{os.pathsep}{os.environ.get('PATH', '')}"
        os.environ["FAKE_GH_LOG"] = str(self.log)
        os.environ["FAKE_GH_COUNTS"] = json.dumps(self.counts)
        os.environ["FAKE_GH_WORKFLOWS"] = self.workflows
        if self.fail_mode:
            os.environ["FAKE_GH_FAIL_MODE"] = self.fail_mode
        return self

    def __exit__(self, *_exc_info):
        os.environ.clear()
        os.environ.update(self._saved)
        self.tmp.cleanup()
        return False

    def commands(self):
        return [ln for ln in self.log.read_text(encoding="utf-8").splitlines() if ln]


class TestNoSubtraction(unittest.TestCase):
    """The load-bearing class: skipped runs are not failures."""

    def test_skip_only_workflow_is_CLEAN_not_born_broken(self):
        # total=100, success=0, skipped=100. `total - success` = 100 "failures".
        counts = {b: 0 for b in wrc.BUCKETS}
        counts["skipped"] = 100
        self.assertEqual(wrc.verdict(counts), "CLEAN")

    def test_cancelled_only_workflow_is_CLEAN(self):
        # A cancelled run was superseded by concurrency; it is not a failure.
        counts = {b: 0 for b in wrc.BUCKETS}
        counts["cancelled"] = 40
        self.assertEqual(wrc.verdict(counts), "CLEAN")

    def test_zero_success_with_real_failures_is_BORN_BROKEN(self):
        counts = {b: 0 for b in wrc.BUCKETS}
        counts["failure"] = 50
        self.assertEqual(wrc.verdict(counts), "BORN-BROKEN")

    def test_one_success_alongside_failures_is_MIXED_not_born_broken(self):
        # The discriminator between "never worked" and "regressed". A single
        # success means a last-good commit exists and bisect is valid.
        counts = {b: 0 for b in wrc.BUCKETS}
        counts["success"] = 1
        counts["failure"] = 943
        self.assertEqual(wrc.verdict(counts), "MIXED")

    def test_in_flight_only_is_NO_TERMINAL_RUNS_not_clean(self):
        # Nothing has concluded, so "clean" would be an unearned all-clear.
        counts = {b: 0 for b in wrc.BUCKETS}
        counts["in_progress"] = 3
        counts["queued"] = 2
        self.assertEqual(wrc.verdict(counts), "NO-TERMINAL-RUNS")

    def test_skipped_is_not_in_the_failing_set(self):
        self.assertNotIn("skipped", wrc.FAILING)
        self.assertNotIn("cancelled", wrc.FAILING)

    def test_startup_failure_only_lane_is_BORN_BROKEN(self):
        # A workflow whose YAML never parsed has never once succeeded. If
        # startup_failure were not counted, this would read as
        # NO-TERMINAL-RUNS — an unearned "nothing to see here" on a lane that
        # has never worked.
        counts = {b: 0 for b in wrc.BUCKETS}
        counts["startup_failure"] = 9
        self.assertEqual(wrc.verdict(counts), "BORN-BROKEN")


class TestCoverageResidual(unittest.TestCase):
    """The residual is the only detector for a wrong bucket enum."""

    def test_exact_arithmetic_passes(self):
        counts = {b: 0 for b in wrc.BUCKETS}
        counts.update(success=90, failure=10)
        residual, ok, reason = wrc.coverage(100, counts)
        self.assertEqual(residual, 0)
        self.assertTrue(ok, reason)

    def test_large_unaccounted_population_fails_coverage(self):
        # An enum that cannot see 40% of the population is not a census.
        counts = {b: 0 for b in wrc.BUCKETS}
        counts["success"] = 60
        residual, ok, reason = wrc.coverage(100, counts)
        self.assertEqual(residual, 40)
        self.assertFalse(ok)
        self.assertIn("NOT a census", reason)

    def test_buckets_summing_above_total_is_double_counting(self):
        # This is what adding `completed` to BUCKETS would do: it is a STATUS
        # that every terminal conclusion also satisfies.
        counts = {b: 0 for b in wrc.BUCKETS}
        counts.update(success=90, failure=10)
        residual, ok, reason = wrc.coverage(50, counts)
        self.assertLess(residual, 0)
        self.assertFalse(ok)
        self.assertIn("double-counting", reason)

    def test_completed_is_not_a_bucket(self):
        # Pinning the exclusion itself: `completed` overlaps every terminal
        # conclusion, so its presence would silently double the sum.
        self.assertNotIn("completed", wrc.BUCKETS)

    def test_startup_failure_IS_a_bucket_despite_being_undocumented(self):
        # GitHub's documented `status` enum omits startup_failure, but the
        # filter supports it. Settled by known-positive, not by reading:
        # measured 2026-08-27 on example-org/.github "PR Security Review
        # (Required)" — an exhaustive 297-run walk found exactly 9
        # startup_failure runs, `status=startup_failure` returned 9, and an
        # invalid control status returned 0. Dropping it silently loses a real
        # failing population (it was 9 of 297 runs on that one workflow).
        self.assertIn("startup_failure", wrc.BUCKETS)
        self.assertIn("startup_failure", wrc.FAILING)

    def test_tolerance_derives_from_in_flight_not_a_fixed_constant(self):
        # 12 in-flight runs can legitimately shift the arithmetic well past a
        # hardcoded floor of 2. A fixed tolerance would call this a failure.
        counts = {b: 0 for b in wrc.BUCKETS}
        counts.update(success=100, in_progress=8, queued=4)
        residual, ok, reason = wrc.coverage(100 + 8 + 4 + 20, counts)
        self.assertEqual(residual, 20)
        self.assertTrue(ok, reason)

    def test_tolerance_floor_applies_when_nothing_in_flight(self):
        counts = {b: 0 for b in wrc.BUCKETS}
        counts["success"] = 100
        _, ok_small, _ = wrc.coverage(102, counts)
        _, ok_big, _ = wrc.coverage(140, counts)
        self.assertTrue(ok_small)
        self.assertFalse(ok_big)


class TestGhReading(unittest.TestCase):
    def test_error_body_on_stdout_is_not_read_as_a_count(self):
        # `gh api` writes its error JSON to STDOUT. A count parser that
        # accepted it would turn a 404 into a number.
        with FakeGh(fail_mode="error_body_on_stdout"):
            with self.assertRaises(wrc.GhError) as ctx:
                wrc.run_gh_count("repos/o/r/actions/runs?per_page=1")
        self.assertIn("non-numeric", str(ctx.exception))

    def test_only_documented_bucket_statuses_are_ever_queried(self):
        # No caller-supplied status may reach the API: an unsupported value
        # returns 0, which would read as a real "none".
        counts = {b: 0 for b in wrc.BUCKETS}
        counts[""] = 0
        with FakeGh(counts=counts) as fake:
            wrc.census_one("o/r")
            queried = set()
            for line in fake.commands():
                for token in line.split():
                    if "status=" in token:
                        queried.add(token.split("status=", 1)[1].split("&")[0])
        self.assertTrue(queried)
        self.assertEqual(queried - set(wrc.BUCKETS), set())

    def test_oldest_failure_is_fetched_via_the_last_page(self):
        # The oldest failure comes from the API's own pagination at
        # per_page=1, not a local scan of a truncated page.
        counts = {b: 0 for b in wrc.BUCKETS}
        counts.update({"": 7, "failure": 7})
        with FakeGh(counts=counts) as fake:
            oldest, newest = wrc.failure_span("o/r", 7)
            pages = [ln for ln in fake.commands() if "created_at" in ln]
        self.assertTrue(any("page=7" in p for p in pages))
        self.assertNotEqual(oldest, newest)

    def test_single_failure_does_not_request_page_one_twice(self):
        counts = {b: 0 for b in wrc.BUCKETS}
        counts.update({"": 1, "failure": 1})
        with FakeGh(counts=counts) as fake:
            oldest, newest = wrc.failure_span("o/r", 1)
            pages = [ln for ln in fake.commands() if "created_at" in ln]
        self.assertEqual(len(pages), 1)
        self.assertEqual(oldest, newest)


class TestWorkflowSelection(unittest.TestCase):
    WORKFLOWS = "101\tactive\tValidate Config\n102\tdisabled_manually\tOld Lane"

    def test_no_match_raises_rather_than_reporting_an_empty_census(self):
        counts = {b: 0 for b in wrc.BUCKETS}
        with FakeGh(counts=counts, workflows=self.WORKFLOWS):
            with self.assertRaises(wrc.GhError) as ctx:
                wrc.build_report("o/r", workflow="nonexistent-lane")
        self.assertIn("not an empty census", str(ctx.exception))

    def test_disabled_workflows_are_included(self):
        # "never worked and is now switched off" is a finding, not noise.
        counts = {b: 0 for b in wrc.BUCKETS}
        counts.update({"": 5, "failure": 5})
        with FakeGh(counts=counts, workflows=self.WORKFLOWS):
            report = wrc.build_report("o/r", all_workflows=True)
        names = {r["workflow"] for r in report["rows"]}
        states = {r["workflow"]: r.get("state") for r in report["rows"]}
        self.assertIn("Old Lane", names)
        self.assertEqual(states["Old Lane"], "disabled_manually")

    def test_workflow_names_containing_tabs_survive_parsing(self):
        counts = {b: 0 for b in wrc.BUCKETS}
        with FakeGh(counts=counts, workflows="7\tactive\todd\tname"):
            rows = wrc.list_workflows("o/r")
        self.assertEqual(rows[0]["name"], "odd\tname")


class TestExitCodes(unittest.TestCase):
    def _run(self, counts, workflows="", extra=()):
        with FakeGh(counts=counts, workflows=workflows) as fake:
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--repo", "o/r", *extra],
                capture_output=True, text=True, env=dict(os.environ))
            return proc, fake

    def test_clean_census_exits_zero(self):
        counts = {b: 0 for b in wrc.BUCKETS}
        counts.update({"": 100, "success": 100})
        proc, _ = self._run(counts)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_failed_coverage_exits_three_and_says_do_not_cite(self):
        # A census whose own arithmetic does not close must not be quotable.
        counts = {b: 0 for b in wrc.BUCKETS}
        counts.update({"": 1000, "success": 100})
        proc, _ = self._run(counts)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("do not cite", proc.stderr)

    def test_born_broken_is_named_in_the_report(self):
        counts = {b: 0 for b in wrc.BUCKETS}
        counts.update({"": 900, "failure": 900})
        proc, _ = self._run(counts)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("BORN-BROKEN", proc.stdout)
        self.assertIn("do not bisect", proc.stdout)

    def test_json_mode_emits_parseable_report(self):
        counts = {b: 0 for b in wrc.BUCKETS}
        counts.update({"": 10, "success": 10})
        proc, _ = self._run(counts, extra=("--json",))
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["rows"][0]["counts"]["success"], 10)
        self.assertEqual(payload["rows"][0]["residual_unaccounted"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
