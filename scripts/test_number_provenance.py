#!/usr/bin/env python3
"""Tests for bin/number-provenance-check.py.

Anchored to the REPO via __file__, never to $HOME: on this host ~/.claude IS a
checkout, so a home-derived path silently exercises the DEPLOYED copy and passes
even when the branch lacks the fix (garden's count-and-pin lesson).

Each test names the mutation it kills, so a future reader can tell whether an
assertion is load-bearing or decorative.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
GATE = REPO / "bin" / "number-provenance-check.py"


def run(deliverable_text, evidence_texts, strict=True):
    with tempfile.TemporaryDirectory() as td:
        d = pathlib.Path(td)
        dp = d / "deliverable.md"
        dp.write_text(deliverable_text, encoding="utf-8")
        eps = []
        for i, t in enumerate(evidence_texts):
            ep = d / f"evidence{i}.txt"
            ep.write_text(t, encoding="utf-8")
            eps.append(str(ep))
        cmd = [sys.executable, str(GATE), str(dp), "--json"]
        if eps:
            cmd += ["--evidence", *eps]
        if strict:
            cmd.append("--strict")
        r = subprocess.run(cmd, capture_output=True, text=True)
        return json.loads(r.stdout), r.returncode


class TestGateExists(unittest.TestCase):
    def test_gate_present_and_executable(self):
        self.assertTrue(GATE.is_file(), f"missing {GATE}")


class TestInterpolationTell(unittest.TestCase):
    """Kills: 'for m in HEDGE.finditer(line)' -> 'for m in []'."""

    def test_hedged_quantity_is_hard(self):
        out, rc = run("Blast radius was ~5 of 96 people.", ["5\n96\n"])
        kinds = [f["check"] for f in out["findings"]]
        self.assertIn("interpolation-tell", kinds)
        self.assertEqual(rc, 1)

    def test_the_exact_shape_that_shipped(self):
        """The 2026-08-02 defect, verbatim. Traceable numbers, hedge still fires."""
        out, _ = run("| $N/day | ~5 of 96 touched |", ["500\n5\n96\n"])
        self.assertTrue(any(f["check"] == "interpolation-tell" for f in out["findings"]))

    def test_unhedged_measured_quantity_is_clean(self):
        out, rc = run("Blast radius was 13 of 96 people.", ["13\n96\n"])
        self.assertEqual(out["hard"], 0, out["findings"])
        self.assertEqual(rc, 0)


class TestUntracedQuantity(unittest.TestCase):
    """Kills: the N_OF_M / CURRENCY / PERCENT tracing loops."""

    def test_n_of_m_absent_from_evidence(self):
        out, rc = run("Affected 77 of 412 principals.", ["1\n2\n3\n"])
        self.assertTrue(any(f["check"] == "untraced-quantity" for f in out["findings"]))
        self.assertEqual(rc, 1)

    def test_currency_absent_from_evidence(self):
        out, _ = run("Observed spend was $9,999 last month.", ["12345\n"])
        self.assertTrue(any("9,999" in f["detail"] for f in out["findings"]))

    def test_percent_absent_from_evidence(self):
        out, _ = run("Coverage reached 87% of the fleet.", ["12\n34\n"])
        self.assertTrue(any(f["check"] == "untraced-quantity" for f in out["findings"]))

    def test_cents_evidence_covers_dollar_rendering(self):
        """A measurement in cents must satisfy its dollar rendering, or the
        gate would flag every correctly-derived figure."""
        out, rc = run("The cap is set to $500.00 per day.", ["50000\n"])
        self.assertEqual(out["hard"], 0, out["findings"])
        self.assertEqual(rc, 0)

    def test_thousands_separator_is_normalized(self):
        out, rc = run("Exposure totals $1,670,000 monthly.", ["1670000\n"])
        self.assertEqual(out["hard"], 0, out["findings"])


class TestProposalExemption(unittest.TestCase):
    """Kills: 'if proposal: continue' -> 'if True: continue' (over-broad skip)."""

    def test_a_proposed_cap_is_not_a_measurement_claim(self):
        out, rc = run("We propose a cap of $250 per day.", ["1\n"])
        self.assertEqual(out["hard"], 0, out["findings"])
        self.assertEqual(rc, 0)

    def test_proposal_exemption_does_not_swallow_measurements(self):
        """The exemption must be per-LINE, not global -- otherwise one proposal
        line disables tracing for the whole document."""
        text = ("We propose a cap of $250 per day.\n"
                "Measured blast radius was 77 of 412 people.\n")
        out, rc = run(text, ["250\n"])
        self.assertTrue(any(f["check"] == "untraced-quantity" for f in out["findings"]),
                        "a measurement line after a proposal line must still be traced")
        self.assertEqual(rc, 1)


class TestScopeLimits(unittest.TestCase):
    """The <10% block-rate bar: a gate that flags everything gets ignored."""

    def test_fenced_code_is_exempt(self):
        text = "Example:\n```\namount = 999999\n```\n"
        out, rc = run(text, ["1\n"])
        self.assertEqual(out["hard"], 0, out["findings"])

    def test_inline_code_is_exempt(self):
        out, rc = run("Set `amount: \"999999\"` in the config.", ["1\n"])
        self.assertEqual(out["hard"], 0, out["findings"])

    def test_missing_evidence_file_is_hard(self):
        """Kills a silent-skip on an unreadable evidence path -- otherwise a
        typo'd path makes every number vacuously 'traceable'.

        CONTRACT CHANGE 2026-08-24: the failure MODE moved from a HARD finding
        (exit 1 + JSON) to a loud caller-error REFUSAL (exit 2, no grade) --
        strictly stronger protection for the same intent: a broken evidence
        path can no longer produce ANY verdict, passing or failing."""
        with tempfile.TemporaryDirectory() as td:
            dp = pathlib.Path(td) / "d.md"
            dp.write_text("Total was 77 of 412.", encoding="utf-8")
            r = subprocess.run(
                [sys.executable, str(GATE), str(dp), "--evidence",
                 str(pathlib.Path(td) / "does-not-exist.json"), "--json", "--strict"],
                capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("not a readable file", r.stderr)

    def test_no_evidence_is_advisory_not_hard(self):
        out, rc = run("Total was 77 of 412.", [], strict=True)
        kinds = [f["check"] for f in out["findings"]]
        self.assertIn("uncited-deliverable", kinds)
        advisory = [f for f in out["findings"] if f["check"] == "uncited-deliverable"]
        self.assertEqual(advisory[0]["severity"], "ADVISORY")


class TestStrictSemantics(unittest.TestCase):
    """Kills: 'return 1 if (hard and a.strict) else 0' -> 'return 0'."""

    def test_strict_exits_nonzero_on_hard(self):
        _, rc = run("Affected 77 of 412 principals.", ["1\n"], strict=True)
        self.assertEqual(rc, 1)

    def test_non_strict_exits_zero_even_with_hard_findings(self):
        out, rc = run("Affected 77 of 412 principals.", ["1\n"], strict=False)
        self.assertGreater(out["hard"], 0)
        self.assertEqual(rc, 0, "non-strict must report without failing the build")


class TestRetractionExemption(unittest.TestCase):
    """A doc that records its own corrections must be able to NAME the wrong
    figure. Without this the checker gets LOUDER as the corpus gets more honest
    -- the unsatisfiable-alarm shape `verify-effectiveness.md` warns about.

    Kills: removing the `if RETRACTION.search(line): continue` guard.
    """

    def test_a_retraction_line_may_quote_the_wrong_number(self):
        out, rc = run("v1 asserted ~5 of 96, which was **false**.", ["1\n"])
        self.assertEqual(out["hard"], 0, out["findings"])
        self.assertEqual(rc, 0)

    def test_the_exemption_is_per_line_not_a_bypass(self):
        """The dangerous failure: one retraction line disabling the whole doc."""
        text = ("Blast radius was 77 of 412 people, as v1 said.\n"
                "The measured figure is 99 of 500 principals.\n")
        out, rc = run(text, ["1\n"])
        self.assertTrue(any("500" in f["detail"] for f in out["findings"]),
                        "an untraced claim AFTER a retraction line must still fail")
        self.assertEqual(rc, 1)

    def test_not_measured_marker_is_exempt(self):
        out, rc = run("The 99 of 500 figure was NOT measured.", ["1\n"])
        self.assertEqual(out["hard"], 0, out["findings"])


class TestBrokenEvidenceCallGuard(unittest.TestCase):
    """A mis-called gate must exit 2 (instrumentation error), never grade.

    Kills: removing the a.evidence path-validation guard in main().
    Incident 2026-08-24: `--evidence .` (a directory) counted as one unreadable
    file and every quantity read as untraced — a plausible-looking deliverable
    failure caused entirely by the call shape.
    """

    def _run_raw(self, evidence_args):
        with tempfile.TemporaryDirectory() as td:
            dp = pathlib.Path(td) / "deliverable.md"
            dp.write_text("The cost was $123 total.", encoding="utf-8")
            cmd = [sys.executable, str(GATE), str(dp), "--strict",
                   "--evidence", *evidence_args]
            return subprocess.run(cmd, capture_output=True, text=True)

    def test_directory_as_evidence_exits_2_not_1(self):
        with tempfile.TemporaryDirectory() as td:
            r = self._run_raw([td])
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("not a readable file", r.stderr)

    def test_missing_evidence_file_exits_2(self):
        r = self._run_raw(["/nonexistent/evidence.json"])
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_valid_evidence_still_grades_normally(self):
        out, rc = run("The cost was $123 total.", ["cost 123\n"])
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
