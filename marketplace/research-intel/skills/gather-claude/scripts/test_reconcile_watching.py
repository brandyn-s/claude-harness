#!/usr/bin/env python3
"""Tests for reconcile_watching.py's chunk-failure recovery.

No network: every test replaces the `_run_graphql` seam with a fake that models
`gh api graphql`'s ALL-OR-NOTHING behaviour on an aliased batch.

The defect these pin (measured 2026-08-21, 142-number sweep): one number the
repo cannot resolve made `gh` exit non-zero for the whole 40-alias chunk, and
the old code logged a warning then `continue`d — so 22 numbers were reported as
"NOT FOUND (transferred/deleted)" when 20 were OPEN and one was a real CLOSED
COMPLETED closure that the run therefore never acted on.
"""
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reconcile_watching as rw  # noqa: E402


def _ok(numbers, states):
    """A successful gh response: null node for any number absent from `states`."""
    nodes = []
    for n in numbers:
        s = states.get(n)
        nodes.append(
            "null" if s is None
            else ('{"number": %d, "state": "%s", "stateReason": %s, '
                  '"closedAt": %s}' % (
                      n, s[0],
                      "null" if s[1] is None else '"%s"' % s[1],
                      "null" if s[2] is None else '"%s"' % s[2]))
        )
        nodes[-1] = '"i%d": %s' % (n, nodes[-1])
    body = '{"data": {"repository": {%s}}}' % ", ".join(nodes)
    return subprocess.CompletedProcess([], 0, stdout=body, stderr="")


def _bad_number(n):
    return subprocess.CompletedProcess(
        [], 1, stdout="",
        stderr="gh: Could not resolve to an Issue with the number of %d." % n)


def _transport_error():
    return subprocess.CompletedProcess(
        [], 1, stdout="", stderr="error connecting to api.github.com: timeout")


class BisectRecovery(unittest.TestCase):
    def setUp(self):
        self._real = rw._run_graphql
        self.addCleanup(setattr, rw, "_run_graphql", self._real)

    def test_clean_chunk_resolves_in_one_call(self):
        states = {1: ("OPEN", None, None), 2: ("OPEN", None, None)}
        rw._run_graphql = lambda nums: _ok(nums, states)
        out, unverified, stats = rw.graphql_batch([1, 2])
        self.assertEqual(sorted(out), [1, 2])
        self.assertEqual(unverified, set())
        self.assertEqual(stats["calls"], 1)

    def test_one_unresolvable_number_does_not_void_its_siblings(self):
        """The 2026-08-21 defect. Reverting the bisect makes this fail."""
        POISON = 83731
        states = {
            10: ("OPEN", None, None),
            11: ("CLOSED", "COMPLETED", "2026-08-17T00:00:00Z"),
            12: ("OPEN", None, None),
        }

        def fake(nums):
            if POISON in nums:
                return _bad_number(POISON)
            return _ok(nums, states)

        rw._run_graphql = fake
        nums = [10, 11, POISON, 12]
        out, unverified, stats = rw.graphql_batch(nums)

        # Every resolvable sibling survives...
        self.assertEqual(sorted(out), [10, 11, 12])
        # ...including the COMPLETED closure the old code swallowed.
        self.assertEqual(out[11]["stateReason"], "COMPLETED")
        # ...and only the genuinely bad number is absent.
        self.assertNotIn(POISON, out)
        # A bad number is NOT an unverified number.
        self.assertEqual(unverified, set())
        # Bisecting costs more than one call but stays bounded.
        self.assertGreater(stats["calls"], 1)
        self.assertLessEqual(stats["calls"], 2 * len(nums))

    def test_transport_error_reports_unverified_not_absent(self):
        """Unknown state must never masquerade as 'transferred/deleted'."""
        rw._run_graphql = lambda nums: _transport_error()
        out, unverified, stats = rw.graphql_batch([20, 21, 22])
        self.assertEqual(out, {})
        self.assertEqual(unverified, {20, 21, 22})
        self.assertTrue(stats["errors"])
        # Crucially: NOT bisected into 3 false "bad number" verdicts.
        self.assertEqual(stats["calls"], 1)

    def test_null_node_on_a_successful_call_is_absent_not_unverified(self):
        states = {30: ("OPEN", None, None)}  # 31 omitted -> null node
        rw._run_graphql = lambda nums: _ok(nums, states)
        out, unverified, _ = rw.graphql_batch([30, 31])
        self.assertEqual(sorted(out), [30])
        self.assertEqual(unverified, set())


class Extraction(unittest.TestCase):
    def test_item_column_only(self):
        text = (
            "## Watching\n"
            "| Item | Notes |\n"
            "| --- | --- |\n"
            "| #12345 / #12346 | prose mentioning PR #99999 |\n"
            "## Next\n"
        )
        self.assertEqual(rw.extract_numbers(text), [12345, 12346])


class ClassifyClosed(unittest.TestCase):
    """Row classification: prunable rows vs annotate-siblings vs residue.

    Three consecutive runs (2026-07-24, 2026-08-06, 2026-08-22) hand-derived
    this per-row split after the number-list output invited a wrong prune
    count; these tests pin the in-script classification.
    """

    TEXT = (
        "## Watching\n"
        "| Item | Notes |\n"
        "| --- | --- |\n"
        "| #10000 | standalone row |\n"
        "| #20000 / #20100 | cluster row, no annotation |\n"
        "| #30000 / #30100 | canonical open; #30100 closed NOT_PLANNED (annotated) |\n"
        "| #40000 / #40100 | canonical open; sibling not yet marked |\n"
        "## Next\n"
    )

    def test_standalone_closed_row_is_prunable(self):
        prunable, actionable, residue = rw.classify_closed(self.TEXT, [10000])
        self.assertEqual([nums for nums, _ in prunable], [[10000]])
        self.assertEqual(actionable, [])
        self.assertEqual(residue, [])

    def test_all_closed_cluster_row_is_prunable(self):
        prunable, actionable, residue = rw.classify_closed(self.TEXT, [20000, 20100])
        self.assertEqual([nums for nums, _ in prunable], [[20000, 20100]])
        self.assertEqual(actionable, [])

    def test_annotated_sibling_is_residue_not_actionable(self):
        prunable, actionable, residue = rw.classify_closed(self.TEXT, [30100])
        self.assertEqual(prunable, [])
        self.assertEqual(actionable, [])
        self.assertEqual(residue, [30100])

    def test_unannotated_sibling_is_actionable(self):
        prunable, actionable, residue = rw.classify_closed(self.TEXT, [40100])
        self.assertEqual(prunable, [])
        self.assertEqual(actionable, [40100])
        self.assertEqual(residue, [])

    def test_partially_closed_cluster_is_never_prunable(self):
        # 200 closed, 201 still open -> the row must NOT appear prunable.
        prunable, actionable, residue = rw.classify_closed(self.TEXT, [20000])
        self.assertEqual(prunable, [])
        self.assertEqual(actionable, [20000])

    def test_bare_number_input_is_never_silently_dropped(self):
        prunable, actionable, residue = rw.classify_closed("#50000 #50100", [50000])
        self.assertEqual(prunable, [])
        self.assertIn(50000, actionable)


if __name__ == "__main__":
    unittest.main()
