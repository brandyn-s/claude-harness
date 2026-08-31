#!/usr/bin/env python3
"""Tests for reconcile_observed.py — the live-data reconciliation leg.

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
    prevent.
  * An Athena failure MUST raise, never return []. An empty observed set would
    mark every documented fact DOC_ONLY and hide every UNDOCUMENTED one, i.e. a
    query failure would render as perfect reconciliation.

stdlib only; no AWS and no network are touched.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

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
        today 400s forever (mcp-infra #718 looped 12x/hour for four days)."""
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


class ReconcileTests(unittest.TestCase):
    def test_live_but_undocumented_is_flagged(self):
        """Fixtures use the REAL naming conventions of each side: the baseline holds
        fully-qualified `claude_code.x` (as the docs write it) while Athena's
        event_name column holds the bare suffix. A bare-name baseline fixture would
        pass while hiding the normalization the live run actually needs."""
        kb = _kb({"otel-events": ["claude_code.api_error", "claude_code.tool_result"]})
        rec = R.reconcile(kb, {"otel-events": ["api_error", "tool_result",
                                               "subagent_completed"]})
        self.assertEqual(rec["otel-events"]["status"], R.UNDOCUMENTED)
        self.assertEqual(rec["otel-events"]["undocumented"],
                         ["claude_code.subagent_completed"])

    def test_naming_convention_mismatch_is_not_reported_as_drift(self):
        """THE regression this normalizer exists for. Docs write
        `claude_code.api_error`; Athena stores `api_error`. Without normalization
        the reconciler reported ALL 25 observed events as UNDOCUMENTED and would
        have written 25 duplicate bare-name rows into the baseline plus a permanent
        false DRIFT — caught only because 25 implausibly equalled the whole
        observed set."""
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

    def test_documented_but_unobserved_is_NOT_flagged_as_a_gap(self):
        """DOC_ONLY is informational. Treating it as a gap inflates every
        coverage denominator — 412 documented activity types vs 139 we emit."""
        kb = _kb({"activity-types": ["x", "y", "z"]})
        rec = R.reconcile(kb, {"activity-types": ["x"]})
        self.assertEqual(rec["activity-types"]["status"], R.RECONCILED)
        self.assertEqual(rec["activity-types"]["doc_only_count"], 2)

    def test_exit_code_is_nonzero_only_when_undocumented_exists(self):
        kb = _kb({"otel-events": ["claude_code.a"]})
        obs = kb / "obs.json"
        obs.write_text(json.dumps({"otel-events": ["a"]}), encoding="utf-8")
        self.assertEqual(R.main(["--kb", str(kb), "--observed", str(obs)]), 0)
        obs.write_text(json.dumps({"otel-events": ["a", "new"]}), encoding="utf-8")
        self.assertEqual(R.main(["--kb", str(kb), "--observed", str(obs)]), 1)

    def test_missing_baseline_is_NO_BASELINE_not_all_undocumented(self):
        kb = _kb({})
        rec = R.reconcile(kb, {"otel-events": ["a", "b"]})
        self.assertEqual(rec["otel-events"]["status"], R.NO_BASELINE)


class AthenaFailureTests(unittest.TestCase):
    def test_query_failure_raises_rather_than_returning_empty(self):
        """An empty observed set would mark everything DOC_ONLY and hide every
        UNDOCUMENTED value — a failed query rendering as perfect reconciliation."""
        with mock.patch.object(R, "_aws", return_value=(1, "", "AccessDenied")):
            with self.assertRaises(RuntimeError):
                R.athena_query("SELECT 1", "p")

    def test_paginator_is_bounded(self):
        src = Path(R.__file__).read_text(encoding="utf-8")
        self.assertIn("refusing to loop", src,
                      "an unbounded paginator can spin forever on a bad NextToken")

    def test_update_baseline_records_provenance(self):
        kb = _kb({"otel-events": ["a"]})
        R.write_baseline(kb, "otel-events", ["a", "b"], "2026-07-28", "live-observed")
        d = json.loads((kb / "reference" / "claude-data-channels" / "baselines"
                        / "otel-events.json").read_text(encoding="utf-8"))
        self.assertEqual(d["values"], ["a", "b"])
        self.assertEqual(d["observed_source"], "live-observed",
                         "a value learned from OUR telemetry is not a vendor claim")


class ObservedQueryHygieneTests(unittest.TestCase):
    """Every observed query must be PARTITION-SCOPED and its values IDENTIFIER-SHAPED.

    Measured 2026-08-02, both halves on the first real execution of this leg:

    1. The `cc-analytics-fields` query referenced a `record` column that does not
       exist -> COLUMN_NOT_FOUND, which is why the whole Athena leg had never run.
    2. Unscoped, `SELECT DISTINCT event_name FROM claude_code_events` returned
       **12,431** values against a 29-value baseline -- not event names but LOG
       CONTENT ("AbsLogFile : C:\\Users\\...\\zenserver.log"), because
       otel-flat-views.tf COALESCEs event.name down to body.stringvalue and old
       records carried no event.name. With a partition predicate over the same 15
       days: **198** values, zero containing a space. The contamination is entirely
       HISTORICAL -- an unscoped query is not a more complete census, it is a
       dirtier one -- and `--update-baseline` would have written all 12,431 in.

    That is the mirror of the phantom-REMOVAL bug in diff_channels.py: same root
    shape (comparing sets assembled from different populations), opposite sign.
    """

    def test_every_observed_query_is_partition_scoped(self):
        for key, sql in R.OBSERVED_SCHEMA.items():
            with self.subTest(key=key):
                self.assertIn("year*10000", sql,
                              "an unscoped DISTINCT scans all history: dirtier AND "
                              "more expensive on a lake billing ~$5k/21d")
                self.assertIn(str(R.OBSERVED_FLOOR_YMD), sql)

    def test_a_newly_added_value_gets_PER_VALUE_provenance(self):
        """A value added to `values` but absent from `observed_values` is reported
        as a phantom REMOVAL by diff_channels.py on every later run — the bug
        claude-config #1864 fixed, reintroduced from the writer's side. Measured
        2026-08-02: this writer added 5 such values before the fix."""
        kb = _kb({"activity-types": ["already_documented"]})
        R.write_baseline(kb, "activity-types",
                         ["already_documented", "brand_new_observed"],
                         "2026-08-02", "docs + live-observed reconciliation")
        d = json.loads((kb / "reference" / "claude-data-channels" / "baselines"
                        / "activity-types.json").read_text(encoding="utf-8"))
        self.assertIn("brand_new_observed", d["values"])
        self.assertIn("brand_new_observed", d["observed_values"],
                      "a telemetry-learned value MUST be held out of the docs diff")
        self.assertNotIn("already_documented", d["observed_values"],
                         "a value the docs already carried stays docs-sourced")

    def test_provenance_never_lists_a_value_absent_from_values(self):
        """A stale observed_values entry would invent a phantom held-out member."""
        kb = _kb({"activity-types": ["a", "b"]})
        R.write_baseline(kb, "activity-types", ["a", "b"], "2026-08-02", "src",
                         newly_observed=["b", "gone"])
        d = json.loads((kb / "reference" / "claude-data-channels" / "baselines"
                        / "activity-types.json").read_text(encoding="utf-8"))
        self.assertEqual(d["observed_values"], ["b"])

    def test_the_otel_query_is_scoped_to_ONE_service(self):
        """`claude_code_events` carries FIVE services with different event
        vocabularies. Unscoped, the reconciler reported 169 UNDOCUMENTED events —
        all of them Claude DESKTOP's — and NORMALIZERS would have prefixed each with
        `claude_code.` before writing them into a baseline scoped to Claude CODE's
        doc page. Measured 2026-08-02: desktop 169 distinct, code 25."""
        self.assertIn("service_name = 'claude-code'", R.OBSERVED_SCHEMA["otel-events"])

    def test_no_observed_query_references_a_nonexistent_record_column(self):
        """The exact defect that made this leg fail on its first real run."""
        for key, sql in R.OBSERVED_SCHEMA.items():
            with self.subTest(key=key):
                self.assertNotIn("map_keys(record)", sql)

    def test_log_content_is_rejected_as_a_fact(self):
        """These are REAL values the unscoped query returned."""
        for bad in ("  AbsLogFile            : C:\\Users\\x\\zenserver.log",
                    "  AsioVersion           : 1.38.0",
                    "  ChildId               : Zen_20208_Startup",
                    "", "x" * (R.MAX_IDENTIFIER_LEN + 1)):
            with self.subTest(value=bad[:30]):
                self.assertFalse(R.looks_like_identifier(bad))

    def test_real_identifiers_survive_the_filter(self):
        """The negative control: without it, a filter rejecting EVERYTHING would
        pass the test above and silently empty the observed set."""
        for good in ("claude_code.user_prompt", "api_refusal", "claude_file_uploaded",
                     "claude_code.subagent_completed", "role_assignment_granted"):
            with self.subTest(value=good):
                self.assertTrue(R.looks_like_identifier(good))

    def test_json_key_set_walks_arbitrary_depth(self):
        """Real shapes measured from code_analytics: core_metrics nests one level,
        model_breakdown is an ARRAY of objects. A SQL-side unnest has to commit to
        a depth; this must not."""
        keys = R.json_key_set([
            '{"num_sessions":0,"lines_of_code":{"added":37,"removed":5}}',
            '[{"model":"opus","estimated_cost":{"amount":1,"currency":"USD"}}]',
        ])
        for expected in ("num_sessions", "lines_of_code", "added", "removed",
                         "model", "estimated_cost", "amount", "currency"):
            self.assertIn(expected, keys)

    def test_json_key_set_flags_a_malformed_blob_rather_than_dropping_it(self):
        self.assertIn("__MALFORMED__", R.json_key_set(['{"a":1}', "not json"]))
        self.assertNotIn("__MALFORMED__", R.json_key_set(['{"a":1}', "", None]))

    def test_header_row_is_derived_from_the_query_not_an_allowlist(self):
        """A hand-maintained allowlist silently keeps a NEW query's header as a
        DATA value, which then reads as a live observed fact."""
        self.assertEqual(R._selected_column_name("SELECT DISTINCT type FROM activities"), "type")
        self.assertEqual(
            R._selected_column_name("SELECT core_metrics FROM code_analytics WHERE x"),
            "core_metrics")
        self.assertIsNone(
            R._selected_column_name("SELECT json_extract_scalar(actor,'$.t') FROM activities"),
            "an unparseable SELECT must fall back, never guess")


class AthenaTimeoutBudgetTests(unittest.TestCase):
    """Run 5: the shipped 240 s budget made the whole leg unrunnable — the
    otel-events query scans 228 GB and SUCCEEDED at ~460 s, so main() returned 2
    before reaching the diff. A fixed budget on a growing table is a time bomb."""

    def test_default_budget_exceeds_the_measured_runtime(self):
        # 460 s measured 2026-08-11; require real headroom, not a hair's breadth.
        self.assertGreaterEqual(R.DEFAULT_ATHENA_TIMEOUT_S, 600)

    def test_athena_query_default_is_the_named_constant_not_a_literal(self):
        import inspect

        sig = inspect.signature(R.athena_query)
        self.assertEqual(sig.parameters["timeout_s"].default, R.DEFAULT_ATHENA_TIMEOUT_S)

    def test_collect_observed_threads_the_budget_to_the_batch(self):
        """A partially-threaded timeout leaves some leg on the old default,
        so the run still dies — just later and more confusingly."""
        seen = []

        def fake(sqls, profile, timeout_s=R.DEFAULT_ATHENA_TIMEOUT_S):
            seen.append(timeout_s)
            return {k: ["{}"] for k in sqls}

        with mock.patch.object(R, "athena_query_many", fake):
            R.collect_observed("p", 777)
        self.assertTrue(seen, "no batch was issued")
        self.assertEqual(set(seen), {777},
                         f"some call site kept a different budget: {sorted(set(seen))}")

    def test_collect_observed_issues_ONE_concurrent_batch(self):
        """The wall-clock win: all scans must go in a single athena_query_many
        call (start all, then poll), not N serial athena_query calls. Run 6
        measured the serial form as the run's dominant cost (~3-8 min/query)."""
        batches = []

        def fake_many(sqls, profile, timeout_s=R.DEFAULT_ATHENA_TIMEOUT_S):
            batches.append(dict(sqls))
            return {k: ["{}"] for k in sqls}

        with mock.patch.object(R, "athena_query_many", fake_many), \
             mock.patch.object(R, "athena_query",
                               side_effect=AssertionError("serial call issued")):
            R.collect_observed("p")
        self.assertEqual(len(batches), 1, "expected exactly one concurrent batch")
        # The batch must contain every schema query AND the extra JSON-blob columns.
        for key in R.OBSERVED_SCHEMA:
            self.assertIn(key, batches[0])
        for key, extra in R.FLATTEN_JSON_KEYS.items():
            for col in extra[1:]:
                self.assertIn(f"{key}::{col}", batches[0])

    def test_poll_all_starts_everything_before_polling(self):
        """start-query-execution for EVERY query must precede the first
        get-query-execution, or the batch degenerates back to serial."""
        calls = []

        def fake_aws(args, profile):
            calls.append(args[1])
            if args[1] == "start-query-execution":
                return 0, json.dumps({"QueryExecutionId": f"q{len(calls)}"}), ""
            if args[1] == "get-query-execution":
                return 0, json.dumps(
                    {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}), ""
            return 0, json.dumps({"ResultSet": {"Rows": []}}), ""

        with mock.patch.object(R, "_aws", fake_aws), \
             mock.patch.object(R.time, "sleep"):
            R.athena_query_many({"a": "SELECT x FROM t", "b": "SELECT y FROM t"}, "p")
        first_poll = calls.index("get-query-execution")
        self.assertEqual(calls[:first_poll].count("start-query-execution"), 2,
                         "second query was not started before polling began")

    def test_poll_all_deadline_names_every_still_running_query(self):
        def fake_aws(args, profile):
            if args[1] == "get-query-execution":
                return 0, json.dumps(
                    {"QueryExecution": {"Status": {"State": "RUNNING"}}}), ""
            return 0, "{}", ""

        with mock.patch.object(R, "_aws", fake_aws), \
             mock.patch.object(R.time, "sleep"), \
             mock.patch.object(R.time, "monotonic", side_effect=[0, 1, 2, 999]):
            with self.assertRaises(RuntimeError) as cm:
                R.athena_poll_all({"slow-one": "qid123"}, "p", timeout_s=10)
        msg = str(cm.exception)
        self.assertIn("qid123", msg, "the still-running qid must be pollable by hand")
        self.assertIn("STILL RUNNING", msg.upper().replace("MAY STILL BE RUNNING",
                                                           "STILL RUNNING"))


class WatchChecksTests(unittest.TestCase):
    """--watch: the previously hand-run Watching-table lake checks (run 6).

    Run 6's hand versions guessed two column names and used the vendor's
    prefixed event names against a lake that stores bare names — three wasted
    Athena round-trips. The canned queries pin the measured contract."""

    def test_watch_queries_use_bare_event_names(self):
        """The lake stores `retention_sweep`, not `claude_code.retention_sweep`
        (the flat view strips the prefix; NORMALIZERS re-adds it only for the
        baseline comparison). A prefixed name here returns a false zero."""
        q = R.watch_queries()
        self.assertIn("event_name = 'retention_sweep'", q["retention-sweep"])
        self.assertNotIn("claude_code.retention_sweep", q["retention-sweep"])

    def test_watch_queries_are_partition_scoped(self):
        for key, sql in R.watch_queries().items():
            with self.subTest(key=key):
                self.assertIn("year*10000", sql)

    def test_desktop_rename_alarms_and_appearances_do_not(self):
        kb = _kb({R.DESKTOP_BASELINE_KEY: ["lam_a", "lam_b"]})
        with mock.patch.object(R, "athena_query_many", return_value={
            "desktop-vocabulary": ["lam_a", "lam_new1", "lam_new2"],  # lam_b GONE
            "credential-pair": [],
            "retention-sweep": [],
        }):
            report, alarm = R.run_watch(kb, "p")
        self.assertTrue(alarm)
        self.assertEqual(report["desktop-vocabulary"]["missing_baselined"], ["lam_b"])
        self.assertEqual(report["desktop-vocabulary"]["unbaselined_count"], 2,
                         "appearances are REPORTED for reading, never auto-alarmed")

    def test_credential_pair_threshold_crossing_alarms(self):
        kb = _kb({R.DESKTOP_BASELINE_KEY: ["lam_a"]})
        with mock.patch.object(R, "athena_query_many", return_value={
            "desktop-vocabulary": ["lam_a"],
            "credential-pair": ["custom3p_credential_heal|150|3"],
            "retention-sweep": [],
        }):
            report, alarm = R.run_watch(kb, "p")
        self.assertTrue(alarm)
        self.assertTrue(report["credential-pair"]["custom3p_credential_heal"]["crossed"])

    def test_credential_pair_below_threshold_is_quiet(self):
        kb = _kb({R.DESKTOP_BASELINE_KEY: ["lam_a"]})
        with mock.patch.object(R, "athena_query_many", return_value={
            "desktop-vocabulary": ["lam_a"],
            "credential-pair": ["custom3p_credential_heal|5|5"],
            "retention-sweep": [],
        }):
            _report, alarm = R.run_watch(kb, "p")
        self.assertFalse(alarm)

    def test_unknown_sweep_skip_reason_alarms_known_ones_do_not(self):
        kb = _kb({R.DESKTOP_BASELINE_KEY: ["lam_a"]})
        rows = ["-|30|true|6295|499",
                "user_source_disabled|30|true|14|6",
                "settings_invalid_key_set|30|true|1|1"]   # the #41458 signature
        with mock.patch.object(R, "athena_query_many", return_value={
            "desktop-vocabulary": ["lam_a"],
            "credential-pair": [],
            "retention-sweep": rows,
        }):
            report, alarm = R.run_watch(kb, "p")
        self.assertTrue(alarm)
        flags = {s["skip_reason"]: s["unknown_reason"] for s in report["retention-sweep"]}
        self.assertFalse(flags["-"])
        self.assertFalse(flags["user_source_disabled"])
        self.assertTrue(flags["settings_invalid_key_set"])

    def test_fleet_norm_used_default_true_does_NOT_alarm(self):
        """Finding #23's correction: used_default='true' + period_days=30 is the
        fleet norm (256/264 rows, 64/66 people). Alarming on it would have pinned
        a shared metric to ALARM and muted a real control failure beside it."""
        kb = _kb({R.DESKTOP_BASELINE_KEY: ["lam_a"]})
        with mock.patch.object(R, "athena_query_many", return_value={
            "desktop-vocabulary": ["lam_a"],
            "credential-pair": [],
            "retention-sweep": ["-|30|true|6295|499"],
        }):
            _report, alarm = R.run_watch(kb, "p")
        self.assertFalse(alarm)


class ObservedInputOutputTests(unittest.TestCase):
    def test_missing_observed_input_is_a_clear_error_not_a_traceback(self):
        """Run 6 passed --observed with a nonexistent path (assuming it was a
        SAVE path) and got a raw FileNotFoundError traceback."""
        import contextlib
        import io

        kb = _kb({})
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            rc = R.main(["--kb", str(kb), "--observed", str(kb / "nope.json")])
        self.assertEqual(rc, 2)
        self.assertIn("--save-observed", err.getvalue(),
                      "the error must name the flag that produces the input")

    def test_save_observed_round_trips_through_observed(self):
        import diff_channels as dc_mod

        kb = _kb({"otel-events": ["claude_code.a"]})
        saved = kb / "obs.json"
        batch_result = {k: (["a"] if k == "otel-events" else ["{}"])
                        for k in list(R.OBSERVED_SCHEMA)
                        + ["cc-analytics-fields::tool_actions",
                           "cc-analytics-fields::model_breakdown"]}
        with mock.patch.object(R, "athena_query_many", return_value=batch_result), \
             mock.patch.object(dc_mod, "code_freshness",
                               return_value=("FRESH", "")):
            rc = R.main(["--kb", str(kb), "--save-observed", str(saved)])
        self.assertTrue(saved.exists(), "inventory was not saved")
        rc2 = R.main(["--kb", str(kb), "--observed", str(saved)])
        self.assertEqual(rc, rc2, "offline re-diff disagreed with the live run")

    def test_live_collection_runs_the_code_freshness_gate(self):
        """The gate exists because run 6 executed 143-commit-stale code; a live
        collection with STALE code must refuse (offline --observed is exempt)."""
        import diff_channels as dc_mod

        kb = _kb({})
        with mock.patch.object(dc_mod, "code_freshness",
                               return_value=("STALE", "n commits behind")):
            rc = R.main(["--kb", str(kb)])
        self.assertEqual(rc, 2)

    def test_cli_exposes_a_timeout_override(self):
        import argparse
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.suppress(SystemExit):
            with contextlib.suppress(argparse.ArgumentError):
                R.main(["--help"])
        self.assertIn("--timeout", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
