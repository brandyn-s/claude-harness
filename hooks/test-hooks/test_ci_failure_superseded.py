"""Tests for bin/ci-failure-superseded.py.

The decision function is pure, so every case is testable without network. Each
test pins a real measured case from 2026-07-28 (see the module docstring) —
including the FALSE-DROP CONTROL, which is the whole reason a bare
`headSha != main-HEAD` test was rejected.

Run standalone:  python3 hooks/test-hooks/test_ci_failure_superseded.py
Under pytest:    collected normally (no module-level sys.exit — tdd-quality #14)
"""
import importlib.util
import pathlib
import unittest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "bin" / "ci-failure-superseded.py"


def _load():
    spec = importlib.util.spec_from_file_location("superseded_under_test", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.classify = _load().classify

    # --- the two real superseded cases ---

    def test_mcp_infra_terraform_ahead_20_no_rerun(self):
        """Measured: ahead_by=20, every later Terraform run cancelled/pending.
        The s3:PutInventoryConfiguration grant was already in ci.tf."""
        v, _ = self.classify(20, None)
        self.assertEqual(v, "SUPERSEDED")

    def test_code_search_unit_tests_ahead_3_newer_success(self):
        """Measured: ahead_by=3 AND two later runs green (fixed by #261)."""
        v, _ = self.classify(3, "success")
        self.assertEqual(v, "DROP_SUCCEEDED")

    def test_ahead_3_without_newer_run_is_superseded(self):
        """The threshold case reached via supersession alone, not recency."""
        v, _ = self.classify(3, None)
        self.assertEqual(v, "SUPERSEDED")

    # --- FALSE-DROP CONTROL: the reason a bare sha test was rejected ---

    def test_mcp_servers_dependency_update_ahead_1_is_current(self):
        """Measured: a genuine 12-minute-old failure whose sha ALREADY differed
        from main HEAD (ahead_by=1, no re-run). A bare `headSha != HEAD` rule
        drops this -> false all-clear. MUST stay CURRENT."""
        v, why = self.classify(1, None)
        self.assertEqual(v, "CURRENT", why)

    def test_ahead_2_no_rerun_is_current(self):
        v, _ = self.classify(2, None)
        self.assertEqual(v, "CURRENT")

    def test_ahead_0_is_always_current(self):
        v, why = self.classify(0, None)
        self.assertEqual(v, "CURRENT")
        self.assertIn("main HEAD", why)

    # --- precedence + degenerate inputs ---

    def test_newer_success_wins_over_low_ahead_by(self):
        """Recency is authoritative when present: a green newer run drops the
        failure even at ahead_by=0."""
        v, _ = self.classify(0, "success")
        self.assertEqual(v, "DROP_SUCCEEDED")

    def test_newer_failure_does_not_drop(self):
        """A newer run that also FAILED must not be read as a fix."""
        v, _ = self.classify(1, "failure")
        self.assertEqual(v, "CURRENT")

    def test_unknown_when_compare_failed(self):
        v, _ = self.classify(None, None)
        self.assertEqual(v, "UNKNOWN")

    def test_threshold_is_a_parameter_not_a_magic_number(self):
        self.assertEqual(self.classify(2, None, threshold=2)[0], "SUPERSEDED")
        self.assertEqual(self.classify(2, None, threshold=5)[0], "CURRENT")


class TestBoundary(unittest.TestCase):
    """tdd-quality #8: classification code is boundary-tested AT the threshold."""

    def setUp(self):
        self.mod = _load()

    def test_exact_boundary(self):
        t = self.mod.SUPERSEDED_THRESHOLD
        self.assertEqual(self.mod.classify(t - 1, None)[0], "CURRENT")
        self.assertEqual(self.mod.classify(t, None)[0], "SUPERSEDED")

    def test_default_threshold_is_three(self):
        self.assertEqual(self.mod.SUPERSEDED_THRESHOLD, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
