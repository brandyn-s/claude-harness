#!/usr/bin/env python3
"""Tests for reconcile_observed.py — the probe leg and the observed-inventory leg.

The load-bearing assertions here are the SAFETY ones, because this is the only
script in the skill that makes authenticated calls to a production API:

  * A non-GET probe MUST raise. The operations fact-set enumerates 5 destructive
    compliance endpoints; "probe everything to see what's live" would DELETE
    production chats and projects. Asserted for every non-GET verb, not just
    DELETE, and asserted again at the config level (no compliance channel is in
    the probe set at all — defence in depth).
  * A 400 "field required" MUST classify as REACHABLE. The first run of this
    script reported 0/11 analytics endpoints unreachable on exactly this
    confusion, when all 11 had been verified 200 the same day. That is a
    false-negative machine: it makes a healthy surface look like a gap.
  * A missing key MUST report SKIPPED_NO_KEY, never "unreachable" — conflating an
    instrument gap with a finding is the failure this whole skill exists to
    prevent. Every leg skipped is an instrument problem (exit 2), not coverage.
  * The observed leg reads a plain JSON inventory and nothing else: no cloud
    SDK, no CLI shell-out, no credentials. A missing or malformed inventory is a
    clear exit-2 error — never a traceback, and never an EMPTY observed set,
    which would mark every documented fact DOC_ONLY and hide every UNDOCUMENTED
    one, i.e. render an input failure as perfect reconciliation.

stdlib only; no credentials and no network are touched.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import diff_channels as dc_mod  # module-swapped to the shared engine
import reconcile_observed as R


def _kb(baselines: dict[str, list[str]]) -> Path:
    """A throwaway KB tree with the given baseline files."""
    d = Path(tempfile.mkdtemp())
    b = d / "reference" / "claude-data-channels" / "baselines"
    b.mkdir(parents=True)
    for key, values in baselines.items():
        (b / f"{key}.json").write_text(
            json.dumps({"values": sorted(values), "captured": "2026-07-01"}), encoding="utf-8")
    return d


def _baseline(kb: Path, key: str) -> dict:
    return json.loads((kb / "reference" / "claude-data-channels" / "baselines"
                       / f"{key}.json").read_text(encoding="utf-8"))


def _inventory(kb: Path, data) -> Path:
    p = kb / "observed.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _run(argv: list[str]) -> tuple[int, str, str]:
    """main() with stdout/stderr captured — the CLI is the contract under test."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = R.main(argv)
    return rc, out.getvalue(), err.getvalue()


class ProbeSafetyTests(unittest.TestCase):
    def test_every_non_GET_verb_is_refused(self):
        for method in ("DELETE", "POST", "PUT", "PATCH", "delete", "post"):
            with self.subTest(method=method):
                with self.assertRaises(R.UnsafeProbe):
                    R.probe_endpoint("/v1/compliance/apps/chats/x", "key", method=method)

    def test_only_GET_is_in_the_safe_set(self):
        self.assertEqual(R.PROBE_SAFE_METHODS, {"GET"})

    def test_no_compliance_channel_is_probeable_at_all(self):
        """Defence in depth: even if the verb guard were removed, the probe set
        must not contain the channel whose endpoints are destructive."""
        for key in R.PROBE_ENDPOINTS:
            self.assertNotIn("compliance", key)

    def test_templated_paths_are_not_probed(self):
        """A {placeholder} path needs a real resource id; probing it with the
        literal brace would be a meaningless 404 reported as a gap.

        NOTE the isolation: collect_probes() iterates EVERY channel in
        PROBE_ENDPOINTS, and two of them carry explicit non-templated paths — so
        a fixture that only defines one channel's baseline still probes the other
        two. The first version of this test asserted probe_endpoint was never
        called and blew up on the admin channels' real calls. Scope
        PROBE_ENDPOINTS to the channel under test instead.
        """
        kb = _kb({"analytics-endpoint-paths": ["/v1/organizations/analytics/{id}/x"]})
        only_analytics = {"analytics-endpoint-paths": R.PROBE_ENDPOINTS["analytics-endpoint-paths"]}
        with mock.patch.object(R, "PROBE_ENDPOINTS", only_analytics), \
             mock.patch.object(R, "keychain", return_value="k"), \
             mock.patch.object(R, "probe_endpoint") as pe:
            out = R.collect_probes(kb)
        pe.assert_not_called()
        detail = out["analytics-endpoint-paths"]["detail"]
        self.assertIn("templated", next(iter(detail.values()))[1])


class ClassificationTests(unittest.TestCase):
    def test_400_field_required_is_REACHABLE(self):
        """THE regression that mattered: this is positive evidence the endpoint
        exists and the key is accepted — the request was merely incomplete."""
        v, note = R.classify_probe(400, '{"error":{"message":"date: Field required"}}')
        self.assertEqual(v, "REACHABLE")
        self.assertIn("endpoint exists", note)

    def test_200_is_REACHABLE(self):
        self.assertEqual(R.classify_probe(200, "")[0], "REACHABLE")

    def test_404_is_ABSENT_and_401_403_are_key_problems(self):
        self.assertEqual(R.classify_probe(404, "")[0], "ABSENT")
        self.assertEqual(R.classify_probe(401, "")[0], "WRONG_KEY_CLASS")
        self.assertEqual(R.classify_probe(403, "")[0], "WRONG_SCOPE")

    def test_401_and_403_are_NOT_conflated(self):
        """401 = wrong key TYPE (a different credential is needed); 403 = right
        type, missing scope (a grant is needed). Reading them loosely produced
        three wrong coverage gradings on 2026-07-28."""
        self.assertNotEqual(R.classify_probe(401, "")[0], R.classify_probe(403, "")[0])

    def test_org_type_400_is_its_own_verdict_not_a_gap(self):
        v, _ = R.classify_probe(400, "not supported for this organization type")
        self.assertEqual(v, "ORG_TYPE_UNSUPPORTED")

    def test_summaries_probe_sends_no_limit_param(self):
        """/analytics/summaries REJECTS `limit`, so including it makes a reachable
        endpoint report a permanent 400 — the probe's own param faking a gap."""
        p = R.probe_params_for("/v1/organizations/analytics/summaries")
        self.assertIn("starting_date", p)
        self.assertNotIn("limit", p)

    def test_each_endpoint_family_gets_its_own_date_param(self):
        """Three date-param families in one vendor API; the wrong name is a 400."""
        self.assertIn("date", R.probe_params_for("/v1/organizations/analytics/skills"))
        self.assertIn("starting_date", R.probe_params_for("/v1/organizations/analytics/summaries"))
        self.assertIn("starting_at", R.probe_params_for("/v1/organizations/analytics/cost_report"))

    def test_engagement_probe_respects_the_freshness_floor(self):
        """Engagement endpoints refuse a window newer than ~3 days; asking for
        today 400s forever (a poller once looped 12x/hour for four days)."""
        import datetime
        p = R.probe_params_for("/v1/organizations/analytics/skills")
        asked = datetime.date.fromisoformat(p["date"])
        self.assertGreaterEqual((datetime.date.today() - asked).days, 3)


class MissingKeyTests(unittest.TestCase):
    def test_missing_key_is_SKIPPED_not_unreachable(self):
        kb = _kb({"analytics-endpoint-paths": ["/v1/organizations/analytics/skills"]})
        only_analytics = {"analytics-endpoint-paths": R.PROBE_ENDPOINTS["analytics-endpoint-paths"]}
        with mock.patch.object(R, "PROBE_ENDPOINTS", only_analytics), \
             mock.patch.object(R, "keychain", return_value=None):
            out = R.collect_probes(kb)
        entry = out["analytics-endpoint-paths"]
        self.assertEqual(entry["status"], "SKIPPED_NO_KEY")
        self.assertIn("ANTHROPIC", entry["key_service"])

    def test_keychain_service_names_are_the_documented_ones(self):
        """Two GUESSED service names produced a false 'no local key, BLOCKED'
        verdict on 2026-07-28 when the key was present the whole time."""
        self.assertEqual(R.KEY_SERVICES["analytics"], "ANTHROPIC_CLAUDEAI_ANALYTICS_KEY")
        self.assertEqual(R.KEY_SERVICES["compliance"], "ANTHROPIC_COMPLIANCE_API_KEY")
        self.assertEqual(R.KEY_SERVICES["admin"], "ANTHROPIC_ADMIN_API_KEY")

    def test_keychain_absent_on_a_non_macos_host_reads_as_no_key(self):
        """No `security` binary is the same instrument gap as no item: SKIPPED,
        never a crash and never 'unreachable'."""
        with mock.patch.object(R.subprocess, "run", side_effect=OSError("no security")):
            self.assertIsNone(R.keychain("ANTHROPIC_ADMIN_API_KEY"))

    def test_every_probe_leg_skipped_is_an_instrument_problem(self):
        """A --probe run with no keys at all measured nothing. Exit 2 (instrument),
        never 0 — a green run that probed nothing is the coverage-theater case."""
        kb = _kb({"analytics-endpoint-paths": ["/v1/organizations/analytics/skills"]})
        with mock.patch.object(R, "keychain", return_value=None), \
             mock.patch.object(dc_mod, "code_freshness", return_value=("FRESH", "")):
            rc, _out, err = _run(["--kb", str(kb), "--probe"])
        self.assertEqual(rc, 2)
        self.assertIn("instrument", err.lower())

    def test_one_probed_leg_is_not_an_instrument_gap(self):
        """Partial keys are a normal state: probe what can be probed, report the
        rest SKIPPED, exit 0."""
        kb = _kb({"analytics-endpoint-paths": ["/v1/organizations/analytics/skills"]})

        def only_admin(service):
            return "k" if service == R.KEY_SERVICES["admin"] else None

        with mock.patch.object(R, "keychain", side_effect=only_admin), \
             mock.patch.object(R, "probe_endpoint", return_value=(200, "200")), \
             mock.patch.object(dc_mod, "code_freshness", return_value=("FRESH", "")):
            rc, out, _err = _run(["--kb", str(kb), "--probe"])
        self.assertEqual(rc, 0)
        self.assertIn("[PROBED] admin-endpoint-paths", out)
        self.assertIn("[SKIPPED] analytics-endpoint-paths", out)


class ReconcileTests(unittest.TestCase):
    def test_observed_but_undocumented_is_flagged(self):
        """Fixtures use the REAL naming conventions of each side: the baseline holds
        fully-qualified `claude_code.x` (as the docs write it) while a flattened
        OTel export commonly holds the bare suffix. A bare-name baseline fixture
        would pass while hiding the normalization a real inventory needs."""
        kb = _kb({"otel-events": ["claude_code.api_error", "claude_code.tool_result"]})
        rec = R.reconcile(kb, {"otel-events": ["api_error", "tool_result",
                                               "subagent_completed"]})
        self.assertEqual(rec["otel-events"]["status"], R.UNDOCUMENTED)
        self.assertEqual(rec["otel-events"]["undocumented"],
                         ["claude_code.subagent_completed"])

    def test_naming_convention_mismatch_is_not_reported_as_drift(self):
        """THE regression this normalizer exists for. Docs write
        `claude_code.api_error`; a flattened export stores `api_error`. Without
        normalization the reconciler reported ALL 25 observed events as
        UNDOCUMENTED and would have written 25 duplicate bare-name rows into the
        baseline plus a permanent false DRIFT — caught only because 25
        implausibly equalled the whole observed set."""
        kb = _kb({"otel-events": ["claude_code.api_error", "claude_code.tool"]})
        rec = R.reconcile(kb, {"otel-events": ["api_error", "tool"]})
        self.assertEqual(rec["otel-events"]["status"], R.RECONCILED)
        self.assertEqual(rec["otel-events"]["undocumented"], [])

    def test_normalizer_is_idempotent(self):
        """An already-qualified observed value must not become
        claude_code.claude_code.x."""
        self.assertEqual(R.normalize("otel-events", ["claude_code.tool", "tool"]),
                         ["claude_code.tool"])

    def test_normalizer_only_applies_where_declared(self):
        """activity-types share one convention on both sides; prefixing them would
        corrupt every value."""
        self.assertEqual(R.normalize("activity-types", ["claude_file_uploaded"]),
                         ["claude_file_uploaded"])

    def test_documented_but_unobserved_is_DOC_ONLY_not_a_gap(self):
        """DOC_ONLY is its own informational status (as in the OpenAI sibling), and
        it is NOT a gap: treating it as one inflates every coverage denominator —
        412 documented activity types vs 139 an org actually emits."""
        kb = _kb({"activity-types": ["x", "y", "z"]})
        rec = R.reconcile(kb, {"activity-types": ["x"]})
        self.assertEqual(rec["activity-types"]["status"], R.DOC_ONLY)
        self.assertEqual(rec["activity-types"]["doc_only_count"], 2)
        self.assertEqual(rec["activity-types"]["undocumented"], [])

    def test_exact_match_is_RECONCILED(self):
        kb = _kb({"activity-types": ["x", "y"]})
        rec = R.reconcile(kb, {"activity-types": ["y", "x"]})
        self.assertEqual(rec["activity-types"]["status"], R.RECONCILED)
        self.assertEqual(rec["activity-types"]["doc_only_count"], 0)

    def test_undocumented_outranks_doc_only(self):
        """A fact-set can be both under- and over-documented; the actionable
        half (detector blind) names the status."""
        kb = _kb({"activity-types": ["x", "y"]})
        rec = R.reconcile(kb, {"activity-types": ["x", "new"]})
        self.assertEqual(rec["activity-types"]["status"], R.UNDOCUMENTED)
        self.assertEqual(rec["activity-types"]["doc_only_count"], 1)

    def test_missing_baseline_is_NO_BASELINE_not_all_undocumented(self):
        kb = _kb({})
        rec = R.reconcile(kb, {"otel-events": ["a", "b"]})
        self.assertEqual(rec["otel-events"]["status"], R.NO_BASELINE)


class BaselineWriterTests(unittest.TestCase):
    def test_update_baseline_records_provenance(self):
        kb = _kb({"otel-events": ["a"]})
        R.write_baseline(kb, "otel-events", ["a", "b"], "2026-07-28", "observed")
        d = _baseline(kb, "otel-events")
        self.assertEqual(d["values"], ["a", "b"])
        self.assertEqual(d["observed_source"], "observed",
                         "a value learned from observed data is not a vendor claim")

    def test_a_newly_added_value_gets_PER_VALUE_provenance(self):
        """A value added to `values` but absent from `observed_values` is reported
        as a phantom REMOVAL by diff_channels.py on every later run — the bug
        claude-config #1864 fixed, reintroduced from the writer's side. Measured
        2026-08-02: this writer added 5 such values before the fix."""
        kb = _kb({"activity-types": ["already_documented"]})
        R.write_baseline(kb, "activity-types",
                         ["already_documented", "brand_new_observed"],
                         "2026-08-02", "docs + observed-inventory reconciliation")
        d = _baseline(kb, "activity-types")
        self.assertIn("brand_new_observed", d["values"])
        self.assertIn("brand_new_observed", d["observed_values"],
                      "an observed-only value MUST be held out of the docs diff")
        self.assertNotIn("already_documented", d["observed_values"],
                         "a value the docs already carried stays docs-sourced")

    def test_provenance_never_lists_a_value_absent_from_values(self):
        """A stale observed_values entry would invent a phantom held-out member."""
        kb = _kb({"activity-types": ["a", "b"]})
        R.write_baseline(kb, "activity-types", ["a", "b"], "2026-08-02", "src",
                         newly_observed=["b", "gone"])
        self.assertEqual(_baseline(kb, "activity-types")["observed_values"], ["b"])


class ObservedInventoryHygieneTests(unittest.TestCase):
    """An inventory is produced OUTSIDE this script, from whatever holds the
    deployment's data. Anything that is not identifier-shaped is log content or a
    formatting artefact, not a fact — and writing one into a baseline creates a
    permanent phantom every future diff must carry. Measured 2026-08-02 on a
    flattened OTel export: an unscoped distinct-name census returned 12,431
    "events", most of them log lines."""

    def test_log_content_is_rejected_as_a_fact(self):
        """These are REAL values such a census returned."""
        for bad in ("  AbsLogFile            : C:\\Users\\x\\zenserver.log",
                    "  AsioVersion           : 1.38.0",
                    "  ChildId               : Zen_20208_Startup",
                    "", "x" * (R.MAX_IDENTIFIER_LEN + 1)):
            with self.subTest(value=bad[:30]):
                self.assertFalse(R.looks_like_identifier(bad))

    def test_non_string_json_values_are_not_identifiers(self):
        """A generic JSON inventory can carry nulls or numbers; neither is a fact."""
        for bad in (None, 3, 1.5, ["a"], {"a": 1}):
            with self.subTest(value=repr(bad)):
                self.assertFalse(R.looks_like_identifier(bad))

    def test_real_identifiers_survive_the_filter(self):
        """The negative control: without it, a filter rejecting EVERYTHING would
        pass the test above and silently empty the observed set."""
        for good in ("claude_code.user_prompt", "api_refusal", "claude_file_uploaded",
                     "claude_code.subagent_completed", "role_assignment_granted",
                     "/v1/organizations/analytics/skills"):
            with self.subTest(value=good):
                self.assertTrue(R.looks_like_identifier(good))

    def test_junk_is_dropped_counted_and_never_baselined(self):
        """Dropped values are COUNTED on stderr, never silently filtered — a silent
        filter makes the observed set quietly partial, the failure this whole
        reconciliation exists to prevent wearing the opposite hat."""
        kb = _kb({"otel-events": ["claude_code.a"]})
        inv = _inventory(kb, {"otel-events": ["a", "  AbsLogFile : C:\\x\\zen.log", None]})
        rc, _out, err = _run(["--kb", str(kb), "--observed", str(inv), "--update-baseline"])
        self.assertEqual(rc, 0, "junk must not read as UNDOCUMENTED")
        self.assertIn("dropped 2", err)
        self.assertEqual(_baseline(kb, "otel-events")["values"], ["claude_code.a"],
                         "a non-identifier reached a baseline")


class ObservedInputTests(unittest.TestCase):
    def test_nothing_to_do_without_a_leg_is_an_instrument_problem(self):
        kb = _kb({})
        rc, _out, err = _run(["--kb", str(kb)])
        self.assertEqual(rc, 2)
        self.assertIn("--observed", err)
        self.assertIn("--probe", err)

    def test_missing_observed_input_is_a_clear_error_not_a_traceback(self):
        """Run 6 passed --observed with a nonexistent path and got a raw
        FileNotFoundError traceback. The error must say what the file IS."""
        kb = _kb({})
        rc, _out, err = _run(["--kb", str(kb), "--observed", str(kb / "nope.json")])
        self.assertEqual(rc, 2)
        self.assertIn("does not exist", err)
        self.assertIn("baseline-key", err, "the error must describe the expected shape")

    def test_observed_must_be_an_object_of_lists(self):
        kb = _kb({"otel-events": ["claude_code.a"]})
        for bad in (["a", "b"], {"otel-events": "a"}, {"otel-events": {"a": 1}}, "x", 3):
            with self.subTest(shape=json.dumps(bad)):
                rc, _out, err = _run(["--kb", str(kb), "--observed",
                                      str(_inventory(kb, bad))])
                self.assertEqual(rc, 2)
                self.assertIn("baseline-key", err)

    def test_invalid_json_is_a_clear_error(self):
        kb = _kb({})
        p = kb / "broken.json"
        p.write_text("{not json", encoding="utf-8")
        rc, _out, err = _run(["--kb", str(kb), "--observed", str(p)])
        self.assertEqual(rc, 2)
        self.assertIn("not valid JSON", err)

    def test_exit_code_is_nonzero_only_when_undocumented_exists(self):
        kb = _kb({"otel-events": ["claude_code.a", "claude_code.b"]})
        inv = _inventory(kb, {"otel-events": ["a"]})
        self.assertEqual(_run(["--kb", str(kb), "--observed", str(inv)])[0], 0,
                         "DOC_ONLY is informational, not a failure")
        inv = _inventory(kb, {"otel-events": ["a", "new"]})
        self.assertEqual(_run(["--kb", str(kb), "--observed", str(inv)])[0], 1)

    def test_no_baseline_is_reported_not_failed(self):
        kb = _kb({})
        inv = _inventory(kb, {"otel-events": ["a"]})
        rc, out, _err = _run(["--kb", str(kb), "--observed", str(inv)])
        self.assertEqual(rc, 0)
        self.assertIn("[NO_BASELINE] otel-events", out)

    def test_update_baseline_merges_with_provenance_and_is_idempotent(self):
        """The merge writes the NORMALISED value with per-value provenance, and a
        re-run without --update-baseline must then exit 0 — a non-idempotent
        refresh is a detector bug in a drift costume."""
        kb = _kb({"otel-events": ["claude_code.a"]})
        inv = _inventory(kb, {"otel-events": ["a", "new"]})
        rc, out, _err = _run(["--kb", str(kb), "--observed", str(inv),
                              "--update-baseline", "--run-date", "2026-09-04"])
        self.assertEqual(rc, 0, "a merged UNDOCUMENTED value is resolved, not failed")
        self.assertIn("baseline updated: otel-events", out)
        d = _baseline(kb, "otel-events")
        self.assertEqual(d["values"], ["claude_code.a", "claude_code.new"])
        self.assertEqual(d["observed_values"], ["claude_code.new"])
        self.assertTrue(d["observed_source"])
        self.assertEqual(d["captured"], "2026-09-04")
        self.assertEqual(_run(["--kb", str(kb), "--observed", str(inv)])[0], 0)

    def test_json_output_carries_both_legs(self):
        kb = _kb({"otel-events": ["claude_code.a"]})
        inv = _inventory(kb, {"otel-events": ["a"]})
        out_json = kb / "result.json"
        with mock.patch.object(R, "keychain", return_value="k"), \
             mock.patch.object(R, "probe_endpoint", return_value=(200, "200")), \
             mock.patch.object(dc_mod, "code_freshness", return_value=("FRESH", "")):
            rc, _out, _err = _run(["--kb", str(kb), "--probe", "--observed", str(inv),
                                   "--json", str(out_json)])
        self.assertEqual(rc, 0)
        result = json.loads(out_json.read_text(encoding="utf-8"))
        self.assertEqual(set(result), {"probes", "reconciliation"})
        self.assertEqual(result["reconciliation"]["otel-events"]["status"], R.RECONCILED)
        self.assertIn("admin-endpoint-paths", result["probes"])

    def test_probe_leg_runs_the_code_freshness_gate(self):
        """The gate exists because run 6 executed 143-commit-stale code and
        reproduced a bug already fixed upstream. The probe leg is the live
        instrument, so STALE code refuses it (exit 2)."""
        kb = _kb({})
        with mock.patch.object(dc_mod, "code_freshness",
                               return_value=("STALE", "n commits behind")), \
             mock.patch.object(R, "keychain", return_value="k"):
            rc, _out, err = _run(["--kb", str(kb), "--probe"])
        self.assertEqual(rc, 2)
        self.assertIn("CODE_STALE", err)

    def test_observed_leg_is_exempt_from_the_code_freshness_gate(self):
        """An offline re-diff of a saved inventory touches no instrument that
        staleness can corrupt beyond the diff itself."""
        kb = _kb({"otel-events": ["claude_code.a"]})
        inv = _inventory(kb, {"otel-events": ["a"]})
        with mock.patch.object(dc_mod, "code_freshness",
                               return_value=("STALE", "n commits behind")):
            rc, _out, _err = _run(["--kb", str(kb), "--observed", str(inv)])
        self.assertEqual(rc, 0)


class NoDataStoreSurfaceTests(unittest.TestCase):
    """The observed leg is a file contract. Nothing in this script may query,
    configure, or depend on a particular data store — that is what keeps it
    runnable and testable anywhere."""

    def test_cli_has_no_data_store_flags(self):
        import argparse
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.suppress(SystemExit):
            with contextlib.suppress(argparse.ArgumentError):
                R.main(["--help"])
        text = buf.getvalue()
        for present in ("--probe", "--observed", "--update-baseline", "--json"):
            self.assertIn(present, text)
        for gone in ("--profile", "--timeout", "--watch", "--save-observed", "--probe-only"):
            self.assertNotIn(gone, text)

    def test_module_has_no_cloud_sdk_or_cli_dependency(self):
        src = Path(R.__file__).read_text(encoding="utf-8").lower()
        for token in ("boto3", "botocore", '"aws"', "athena", "workgroup", "query-execution"):
            self.assertNotIn(token, src)
        self.assertNotIn("subprocess.run([\"aws\"", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
