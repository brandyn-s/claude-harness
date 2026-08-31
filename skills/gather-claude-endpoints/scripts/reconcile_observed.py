#!/usr/bin/env python3
"""Reconcile the docs-derived baselines against what our pipeline ACTUALLY observes.

WHY THIS EXISTS — the docs-only blind spot.

`diff_channels.py` asks exactly one source: Anthropic's documentation. That makes
it structurally incapable of finding a surface the docs OMIT. It is a FILTER over
vendor prose, and a filter can only ever return a subset of what it was pointed
at (the enumerate-and-subtract lesson, applied to the detector itself).

Measured 2026-07-28 — the gap this closes:
  * 24 activity types are LIVE in our Compliance feed and absent from the
    412-type baseline, incl. `claude_file_uploaded` (46,860 events, a DLP
    signal), `integration_user_connected`, `platform_agent_created`.
  * `claude_code.subagent_completed` is LIVE in OTel (7,380 events / 1,467
    sessions), absent from the 28-event baseline, and already consumed by
    otel_usage_briefing.py — so a vendor rename would break a live consumer
    with no DRIFT ever firing.

Neither is findable by re-reading docs, because the docs don't mention them. Our
own data is the second authoritative source, and for "what does this org actually
emit" it is the BETTER one: docs describe the product, telemetry describes us.

Verdicts (deliberately distinct from diff_channels.py's, because the ACTION differs):
  UNDOCUMENTED  live-observed, absent from baseline -> the detector is BLIND to it.
                Action: add to the baseline (and consider a detector for it).
  DOC_ONLY      documented, never observed          -> informational. A type the
                product supports but our org never generates is NOT a gap; do not
                treat it as one (that inflates every coverage denominator).
  RECONCILED    observed set is a subset of baseline -> nothing to do.

Deliberately NOT merged into diff_channels.py: that tool must run anywhere with
only network access to docs. This one needs AWS/Athena credentials, so coupling
them would make the doc-drift check fail closed in any environment without AWS —
turning a working detector into an unrunnable one.

Usage:
  reconcile_observed.py --kb <kb-dir> [--observed <json>] [--json OUT]
                        [--update-baseline]

  --observed <json>  a pre-computed observed inventory (see OBSERVED_SCHEMA);
                     when omitted, queries Athena directly.

Exit codes: 0 = reconciled; 1 = UNDOCUMENTED facts found; 2 = instrument problem.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

# An observed inventory is {baseline_key: [observed values]}. Keeping it a plain
# file means the Athena leg can be run once, committed as evidence, and re-diffed
# offline — and it makes this script testable without AWS (the stubbed-seam trap:
# a test that mocks Athena never exercises the SQL, so the query shape is pinned
# by test_reconcile_observed.py against a literal, not just "returns rows").
#: Partition floor for every observed query, as YYYYMMDD. REQUIRED, not an
#: optimisation — and it is the difference between a usable answer and a wrong one.
#:
#: Measured 2026-08-02: unscoped, `SELECT DISTINCT event_name FROM
#: claude_code_events` returned **12,431** values against a 29-value baseline —
#: not event names but LOG-FILE CONTENT from an Unreal Engine tool
#: ("AbsLogFile : C:\\Users\\...\\zenserver.log", "AsioVersion : 1.38.0"), because
#: otel-flat-views.tf COALESCEs `event.name` down to `lr.body.stringvalue` and old
#: records had no event.name attribute. The normalizer then prefixed each with
#: `claude_code.`, manufacturing ~12,400 phantom "events". With a partition
#: predicate over the same 15 days: **198** distinct values, ZERO containing a
#: space. So the contamination is entirely HISTORICAL, and an unscoped query is
#: not a more complete census — it is a dirtier one.
#:
#: `--update-baseline` would have written all 12,431 in. That is the mirror of the
#: phantom-REMOVAL bug this file's sibling fixed: same root shape (comparing sets
#: assembled from different populations), opposite direction.
#:
#: Cost matters too: these are full-table DISTINCT scans on a lake where Athena +
#: CloudTrail data events measured $5,026.94 over 21 days (mcp-infra CLAUDE.md).
OBSERVED_FLOOR_YMD = 20260719

OBSERVED_SCHEMA = {
    "activity-types": (
        "SELECT DISTINCT type FROM activities "
        f"WHERE (year*10000+month*100+day) >= {OBSERVED_FLOOR_YMD}"
    ),
    "activity-actor-types": (
        "SELECT DISTINCT json_extract_scalar(actor,'$.type') FROM activities "
        f"WHERE (year*10000+month*100+day) >= {OBSERVED_FLOOR_YMD}"
    ),
    # SERVICE-SCOPED, and this is load-bearing. The `claude_code_events` table
    # carries FIVE services, each with its own event vocabulary (measured
    # 2026-08-02 over 15 days):
    #     claude-desktop       169 distinct events   489,669 ev
    #     claude-code           25                 8,382,447
    #     cowork                20                   713,877
    #     claude-code-desktop   19                   401,653
    #     canary-recall-probe    4                       294
    # This baseline is scoped to `monitoring-usage.md`, which documents Claude
    # CODE. Unscoped, the reconciler reported 169 UNDOCUMENTED events — every one
    # of them Claude DESKTOP's (`desktop_*`, `lam_*`, `chrome_bridge_*`,
    # `cowork_*`) — and NORMALIZERS would have prefixed each with `claude_code.`
    # before writing them in, permanently filing another product's vocabulary
    # under this one. Scoped to claude-code: 25 values, all genuine event names
    # against a 29-value baseline.
    #
    # Desktop's vocabulary is a real and much larger surface (see
    # claude-desktop-otel-identity-gap), but it needs its OWN fact-set with its own
    # doc source — not a merge into this one. Silence about it here is deliberate,
    # not an oversight.
    "otel-events": (
        "SELECT DISTINCT event_name FROM claude_code_events "
        f"WHERE (year*10000+month*100+day) >= {OBSERVED_FLOOR_YMD} "
        "AND service_name = 'claude-code'"
    ),
    # Fields are a per-record key set, not a column — a NEW vendor field
    # (inference_geo, rbac_group_id) must show up as UNDOCUMENTED instead of
    # silently arriving inside a JSON blob nobody re-reads.
    #
    # 2026-08-02: the previous SQL was `UNNEST(map_keys(record))`, and there is no
    # `record` column — the query failed COLUMN_NOT_FOUND on its FIRST real
    # execution, which is why this whole leg had never run. `code_analytics`
    # carries three JSON-string columns instead, and they are three DIFFERENT
    # shapes (measured, not assumed):
    #     core_metrics    JSON object, nested one level ({"lines_of_code":{...}})
    #     tool_actions    JSON object, nested one level ({"edit_tool":{...}})
    #     model_breakdown JSON ARRAY of objects
    # Three failed casts in a row taught that: cast(x AS json) on a varchar that
    # already holds JSON double-encodes it, and cast(<array> AS map) errors.
    # Rather than hand-roll ever-deeper UNNESTs in SQL (one per nesting level,
    # silently truncating at whatever depth was written), return the raw blobs and
    # flatten in Python — see FLATTEN_JSON_KEYS below. That handles arbitrary
    # depth and matches the baseline, which is a FLATTENED union of top-level
    # columns and nested field names (`core_metrics` AND `added` both appear).
    "cc-analytics-fields": (
        "SELECT core_metrics FROM code_analytics "
        f"WHERE (year*10000+month*100+day) >= {OBSERVED_FLOOR_YMD} "
        "AND core_metrics IS NOT NULL LIMIT 500"
    ),
}

#: A value that cannot be an identifier — a space, or implausible length — is
#: LOG CONTENT that leaked through the view's COALESCE fallback, not a fact. Such a
#: value is DROPPED and COUNTED, never silently kept: writing one into a baseline
#: creates a permanent phantom that every future diff must carry.
MAX_IDENTIFIER_LEN = 80


def looks_like_identifier(v: str) -> bool:
    return bool(v) and " " not in v and len(v) <= MAX_IDENTIFIER_LEN

#: Baseline keys whose observed values are the KEY SET of returned JSON blobs
#: rather than the values themselves. Maps key -> the extra columns to union in.
#: Each column is queried separately because they hold different JSON shapes and
#: a UNION ALL in SQL would force a single cast that cannot fit all three.
FLATTEN_JSON_KEYS = {
    "cc-analytics-fields": ("core_metrics", "tool_actions", "model_breakdown"),
}


def json_key_set(blobs: list[str]) -> set[str]:
    """Every key name at every depth across a list of JSON strings.

    Depth-agnostic on purpose: the field set is what we diff, and a vendor is as
    likely to add a field two levels down (inside `lines_of_code`) as at the top.
    A SQL-side unnest has to commit to a depth; this does not.
    """
    found: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                found.add(k)
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    for b in blobs:
        if not b:
            continue
        try:
            walk(json.loads(b))
        except (json.JSONDecodeError, TypeError):
            # A malformed blob is skipped but COUNTED by the caller — silently
            # dropping it would make the key set quietly partial, which is the
            # same failure this whole reconciliation exists to prevent.
            found.add("__MALFORMED__")
    return found

# Channels whose live truth is a REACHABILITY probe, not a stored inventory: the
# endpoint either answers or it does not. Read-only GET, one call each.
#
# HARD RULE — never probe a DELETE. The operations fact-set now enumerates 5
# destructive compliance endpoints (DELETE on chats, projects, project docs, chat
# files, code artifacts). "Probe every endpoint to see if it's live" would issue
# those against production compliance data. Existence of a DELETE is verified
# from the doc DECLARATION only; it is never exercised.
PROBE_SAFE_METHODS = {"GET"}
PROBE_ENDPOINTS = {
    "admin-endpoint-paths": ("admin", ["/v1/organizations/cost_report",
                                       "/v1/organizations/usage_report/messages"]),
    "analytics-endpoint-paths": ("analytics", None),   # None = probe every baseline value
    "ratelimit-endpoint": ("admin", ["/v1/organizations/rate_limits"]),
}

ATHENA_DB = "mcp_compliance"
ATHENA_WG = "mcp-compliance"
ATHENA_REGION = "us-east-2"

UNDOCUMENTED = "UNDOCUMENTED"
DOC_ONLY = "DOC_ONLY"
RECONCILED = "RECONCILED"
NO_BASELINE = "NO_BASELINE"


def _aws(args: list[str], profile: str) -> tuple[int, str, str]:
    p = subprocess.run(
        ["aws", *args, "--profile", profile, "--region", ATHENA_REGION, "--output", "json"],
        capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


#: Poll budget for one Athena query. Raised 240 -> 900 on 2026-08-11 (run 5) after
#: the shipped 240 s made this whole leg unrunnable: the `otel-events` query scans
#: **228 GB** and SUCCEEDED at ~460 s, so `main()` returned 2 ("INSTRUMENT PROBLEM")
#: before reaching the diff. Step 2c is MANDATORY and is the only leg that can see a
#: surface the docs omit, so a too-small budget silently converts the skill back into
#: a docs-only differ — exactly the blindness this file exists to close. It failed
#: *after* run 4 passed 4/4, i.e. the query grew past a fixed budget; that is why the
#: value is now a named constant with a CLI override instead of a literal.
DEFAULT_ATHENA_TIMEOUT_S = 900


def athena_start(sql: str, profile: str) -> str:
    """Start one Athena query; return its execution id. Raises on failure."""
    rc, out, err = _aws(
        ["athena", "start-query-execution", "--query-string", sql,
         "--query-execution-context", f"Database={ATHENA_DB}", "--work-group", ATHENA_WG], profile)
    if rc:
        raise RuntimeError(f"start-query-execution failed: {err.strip()[:300]}")
    return json.loads(out)["QueryExecutionId"]


def athena_poll_all(qids: dict[str, str], profile: str, timeout_s: int) -> None:
    """Poll a set of already-started queries until ALL succeed.

    This is the wall-clock win behind athena_query_many: queries run
    CONCURRENTLY server-side, so N queries cost ~max(t_i), not sum(t_i).
    Measured 2026-08-22 (run 6): the four OBSERVED_SCHEMA scans took ~3-8 min
    EACH serially — the single largest chunk of the run's wall-clock.

    The budget is SHARED (one deadline for the batch), matching the serial
    semantics a caller of athena_query N times would have wanted anyway: the
    point of the budget is "how long until a human should look", not per-query
    fairness. Raises on the first FAILED/CANCELLED query, and on deadline names
    every still-running qid so each can be polled by hand.
    """
    deadline = time.monotonic() + timeout_s
    pending = dict(qids)  # label -> qid
    while pending and time.monotonic() < deadline:
        time.sleep(2)
        for label, qid in list(pending.items()):
            rc, out, err = _aws(
                ["athena", "get-query-execution", "--query-execution-id", qid], profile)
            if rc:
                raise RuntimeError(f"get-query-execution failed: {err.strip()[:300]}")
            st = json.loads(out)["QueryExecution"]["Status"]
            if st["State"] == "SUCCEEDED":
                del pending[label]
            elif st["State"] in ("FAILED", "CANCELLED"):
                raise RuntimeError(
                    f"query {label} {st['State']}: {st.get('StateChangeReason', '')[:300]}")
    if pending:
        # Very likely STILL RUNNING, not broken — say so, because the useful next
        # action (poll it / raise the budget) is invisible otherwise. Measured
        # 2026-08-11: 228 GB scanned, SUCCEEDED at ~460 s.
        names = ", ".join(f"{k}={v}" for k, v in pending.items())
        raise RuntimeError(
            f"{len(pending)} quer{'y' if len(pending) == 1 else 'ies'} did not finish "
            f"within {timeout_s}s and may still be RUNNING ({names}) — check each with: "
            f"aws athena get-query-execution --query-execution-id <id>. "
            f"If the scans simply grew, re-run with --timeout <seconds>."
        )


def athena_results(qid: str, sql: str, profile: str) -> list[str]:
    """Fetch a SUCCEEDED query's first column as sorted distinct values."""
    values: list[str] = []
    token = None
    pages = 0
    while True:
        pages += 1
        if pages > 200:  # page cap: a paginator with no bound can loop forever
            raise RuntimeError("get-query-results exceeded 200 pages — refusing to loop")
        args = ["athena", "get-query-results", "--query-execution-id", qid, "--max-items", "1000"]
        if token:
            args += ["--starting-token", token]
        rc, out, err = _aws(args, profile)
        if rc:
            raise RuntimeError(f"get-query-results failed: {err.strip()[:300]}")
        d = json.loads(out)
        for row in d["ResultSet"]["Rows"]:
            cell = row["Data"][0].get("VarCharValue") if row.get("Data") else None
            if cell:
                values.append(cell)
        token = d.get("NextToken")
        if not token:
            break
    # Athena echoes the header row as the first result. Match the SELECTed column
    # name, not a hand-maintained allowlist: a new query whose column is absent
    # from the list silently keeps its header as a DATA value, which then reads as
    # a live observed fact (e.g. a literal "core_metrics" row). Derive it instead.
    header = _selected_column_name(sql)
    if values and header and values[0] == header or values and values[0] in ("type", "event_name", "_col0", "k"):
        values = values[1:]
    return sorted(set(values))


def _selected_column_name(sql: str) -> str | None:
    """Best-effort name of the first SELECTed column, for header detection.

    Deliberately simple: it handles `SELECT [DISTINCT] <col> FROM ...`, which is
    every query in OBSERVED_SCHEMA. Returns None on anything more complex so the
    caller falls back to the literal allowlist rather than guessing wrong.
    """
    m = re.search(r"\bselect\s+(?:distinct\s+)?([a-z_][a-z0-9_]*)\s+from\b", sql, re.IGNORECASE | re.DOTALL)
    return m.group(1) if m else None


def athena_query(sql: str, profile: str, timeout_s: int = DEFAULT_ATHENA_TIMEOUT_S) -> list[str]:
    """Run ONE Athena query start-to-results.

    Raises RuntimeError on failure rather than returning [] — an empty result and
    a failed query must never be indistinguishable, because "observed nothing"
    would silently mark every documented fact DOC_ONLY and every live-but-
    undocumented fact invisible. (verify-effectiveness: a health field that
    counts one failure class lets another inflate a normal bucket.)
    """
    qid = athena_start(sql, profile)
    athena_poll_all({"query": qid}, profile, timeout_s)
    return athena_results(qid, sql, profile)


def athena_query_many(sqls: dict[str, str], profile: str,
                      timeout_s: int = DEFAULT_ATHENA_TIMEOUT_S) -> dict[str, list[str]]:
    """Run a BATCH of Athena queries concurrently: start all, poll all, fetch all.

    Same failure contract as athena_query (raise, never return partial), and the
    same shared budget as N serial calls would want — but the wall-clock is
    ~max(t_i) instead of sum(t_i), which run 6 measured as the run's dominant cost.
    """
    qids = {label: athena_start(sql, profile) for label, sql in sqls.items()}
    athena_poll_all(qids, profile, timeout_s)
    return {label: athena_results(qids[label], sqls[label], profile)
            for label in sqls}


def collect_observed(profile: str,
                     timeout_s: int = DEFAULT_ATHENA_TIMEOUT_S) -> dict[str, list[str]]:
    # One concurrent batch: the OBSERVED_SCHEMA scans plus the extra JSON-blob
    # columns (whose SQL depends only on config, not on first-stage results).
    batch: dict[str, str] = dict(OBSERVED_SCHEMA)
    for key, extra in FLATTEN_JSON_KEYS.items():
        for col in extra[1:]:
            batch[f"{key}::{col}"] = (
                f"SELECT {col} FROM code_analytics WHERE {col} IS NOT NULL LIMIT 500"
            )
    results = athena_query_many(batch, profile, timeout_s)

    observed = {}
    for key in OBSERVED_SCHEMA:
        rows = results[key]
        extra = FLATTEN_JSON_KEYS.get(key)
        if extra:
            # These rows are JSON blobs, not values: the observed fact is the KEY
            # SET. Each additional column was queried separately — they hold
            # different JSON shapes, so one UNION ALL would force a cast that
            # fits none.
            blobs = list(rows)
            for col in extra[1:]:
                blobs += results[f"{key}::{col}"]
            keys = json_key_set(blobs)
            if "__MALFORMED__" in keys:
                keys.discard("__MALFORMED__")
                print(f"WARNING: {key}: at least one unparseable JSON blob was skipped",
                      file=sys.stderr)
            # The baseline is a flattened union of COLUMN names and nested FIELD
            # names, so the column names themselves are part of the fact-set.
            observed[key] = sorted(keys | set(extra))
        else:
            # Defence in depth behind OBSERVED_FLOOR_YMD: if the floor is ever
            # lowered, or a NEW extraction defect lands inside the window, a
            # log-content value must still not reach a baseline. Dropped values are
            # COUNTED and printed — a silent filter would make the observed set
            # quietly partial, which is the failure this reconciliation exists to
            # prevent, wearing the opposite hat.
            keep = [v for v in rows if looks_like_identifier(v)]
            if len(keep) != len(rows):
                dropped = [v for v in rows if not looks_like_identifier(v)]
                print(f"WARNING: {key}: dropped {len(dropped)} non-identifier value(s) "
                      f"(log content leaking through the view's COALESCE fallback); "
                      f"first: {dropped[0][:70]!r}", file=sys.stderr)
            observed[key] = keep
    return observed


# --------------------------------------------------------------------------
# --watch: the Watching-table checks that need OUR OWN LAKE, canned (run 6).
# Previously each was a hand-run Athena query re-derived every run; run 6's
# hand versions guessed two column names wrong and used the vendor's prefixed
# event names against a lake that stores bare names (see the naming contract in
# references/athena-lake-contract.md and NORMALIZERS below).
# --------------------------------------------------------------------------

#: Thresholds from finding #22: below this volume, baselining the third-party
#: connector credential pair adds a churn row, not a signal. 5/5 on 2026-08-22.
CRED_EVENTS_THRESHOLD = 100
CRED_PRINCIPALS_THRESHOLD = 20
CRED_EVENTS = ("custom3p_credential_heal", "custom3p_credential_rejected")

#: skip_reason values measured benign (finding #23 + run 6). '-' is the
#: no-skip rollup bucket. A NEW reason — especially settings_invalid_key_set,
#: the documented #41458 signature — is the alarm.
KNOWN_SWEEP_SKIP_REASONS = {"-", "user_source_disabled", "settings_unknowable"}
SWEEP_LOOKBACK_DAYS = 7

DESKTOP_BASELINE_KEY = "desktop-otel-events-security"


def watch_queries() -> dict[str, str]:
    """The three canned lake checks. Event names are BARE (lake convention)."""
    import datetime
    floor = int((datetime.date.today()
                 - datetime.timedelta(days=SWEEP_LOOKBACK_DAYS)).strftime("%Y%m%d"))
    cred_in = ",".join(f"'{e}'" for e in CRED_EVENTS)
    return {
        "desktop-vocabulary": (
            "SELECT DISTINCT event_name FROM claude_code_events "
            "WHERE service_name = 'claude-desktop' "
            f"AND (year*10000+month*100+day) >= {OBSERVED_FLOOR_YMD}"
        ),
        "credential-pair": (
            # one packed column so athena_results' first-column contract holds
            "SELECT r FROM (SELECT event_name || '|' || CAST(count(*) AS varchar) "
            "|| '|' || CAST(count(DISTINCT principal) AS varchar) AS r, count(*) AS n "
            "FROM claude_code_events WHERE service_name = 'claude-desktop' "
            f"AND event_name IN ({cred_in}) "
            f"AND (year*10000+month*100+day) >= {OBSERVED_FLOOR_YMD} "
            "GROUP BY event_name) ORDER BY n DESC"
        ),
        "retention-sweep": (
            "SELECT r FROM (SELECT COALESCE(sweep_skip_reason,'-') || '|' || "
            "CAST(sweep_period_days AS varchar) || '|' || "
            "COALESCE(sweep_used_default,'-') || '|' || CAST(count(*) AS varchar) "
            "|| '|' || CAST(count(DISTINCT principal) AS varchar) AS r, count(*) AS n "
            "FROM claude_code_events WHERE event_name = 'retention_sweep' "
            f"AND (year*10000+month*100+day) >= {floor} "
            "GROUP BY sweep_skip_reason, sweep_period_days, sweep_used_default) "
            "ORDER BY n DESC"
        ),
    }


def run_watch(kb: Path, profile: str,
              timeout_s: int = DEFAULT_ATHENA_TIMEOUT_S) -> tuple[dict, bool]:
    """Run the canned Watching checks; return (report, any_alarm)."""
    res = athena_query_many(watch_queries(), profile, timeout_s)
    report: dict = {}
    alarm = False

    baseline = load_baseline(kb, DESKTOP_BASELINE_KEY) or []
    observed = set(res["desktop-vocabulary"])
    missing = sorted(set(baseline) - observed)
    report["desktop-vocabulary"] = {
        "observed_distinct": len(observed),
        "baselined": len(baseline),
        "missing_baselined": missing,   # a rename — the ONLY detectable signature
        "unbaselined_count": len(observed - set(baseline)),
    }
    if missing:
        alarm = True

    pair = {}
    for row in res["credential-pair"]:
        name, n, p = row.split("|")
        crossed = int(n) >= CRED_EVENTS_THRESHOLD or int(p) >= CRED_PRINCIPALS_THRESHOLD
        pair[name] = {"events": int(n), "principals": int(p), "crossed": crossed}
        if crossed:
            alarm = True
    report["credential-pair"] = pair

    sweep_rows = []
    for row in res["retention-sweep"]:
        skip, days, used_default, n, p = row.split("|")
        bad = skip not in KNOWN_SWEEP_SKIP_REASONS
        sweep_rows.append({"skip_reason": skip, "period_days": days,
                           "used_default": used_default, "rows": int(n),
                           "people": int(p), "unknown_reason": bad})
        if bad:
            alarm = True
    report["retention-sweep"] = sweep_rows
    return report, alarm


def render_watch(report: dict, alarm: bool) -> str:
    lines = ["=" * 72,
             "WATCHING CHECKS (canned lake queries; previously hand-run per run)",
             "=" * 72]
    d = report["desktop-vocabulary"]
    lines.append(f"[desktop-vocabulary] observed {d['observed_distinct']} distinct; "
                 f"{d['baselined']} baselined; {d['unbaselined_count']} unbaselined")
    if d["missing_baselined"]:
        lines.append("    ALARM — baselined security types NO LONGER OBSERVED "
                     "(a rename, the only detectable signature):")
        for m in d["missing_baselined"]:
            lines.append(f"      - {m}")
    else:
        lines.append("    all baselined security types still observed (no rename)")
    lines.append("    NOTE: a materially larger unbaselined count means new types "
                 "appeared — READ the names (finding #22: check appearances, not "
                 "just disappearances)")

    for name, v in report["credential-pair"].items():
        flag = "ALARM — threshold crossed, baseline it" if v["crossed"] else "below threshold"
        lines.append(f"[credential-pair] {name}: {v['events']} events / "
                     f"{v['principals']} principals — {flag} "
                     f"(thresholds {CRED_EVENTS_THRESHOLD}/{CRED_PRINCIPALS_THRESHOLD})")

    lines.append(f"[retention-sweep] last {SWEEP_LOOKBACK_DAYS}d "
                 "(skip|days|used_default|rows|people):")
    for s in report["retention-sweep"]:
        mark = "  <-- ALARM: unknown skip_reason" if s["unknown_reason"] else ""
        lines.append(f"    {s['skip_reason']}|{s['period_days']}|{s['used_default']}"
                     f"|{s['rows']}|{s['people']}{mark}")
    if not report["retention-sweep"]:
        lines.append("    no rows — if the control query also returns rows, the "
                     "event stopped; verify before reading as vendor removal")
    lines.append("")
    lines.append(f"watch verdict: {'ALARM' if alarm else 'clean'}")
    return "\n".join(lines)


class UnsafeProbe(RuntimeError):
    """Raised when something asks to probe a non-GET endpoint. Never caught."""


# Keychain service names, per reference/claude-data-channels/channels/key-types.md.
# NOT guessed — two guessed service names produced a false "no local key, BLOCKED"
# verdict on 2026-07-28 when the key was present all along.
KEY_SERVICES = {
    "admin": "ANTHROPIC_ADMIN_API_KEY",
    "analytics": "ANTHROPIC_CLAUDEAI_ANALYTICS_KEY",
    "compliance": "ANTHROPIC_COMPLIANCE_API_KEY",
}


def keychain(service: str) -> str | None:
    p = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                       capture_output=True, text=True)
    return p.stdout.strip() or None if p.returncode == 0 else None


def classify_probe(status: int | None, body: str) -> tuple[str, str]:
    """Turn an HTTP status into a REACHABILITY verdict.

    The distinction that matters and that a naive probe gets wrong: a
    400 'field required' is POSITIVE evidence the endpoint exists and our key is
    accepted — the request was merely incomplete. An ABSENT endpoint 404s; a wrong
    key CLASS 401s; a wrong SCOPE 403s. Collapsing 400 into "not reachable"
    reported 0/11 analytics endpoints unreachable on the first run of this script,
    when all 11 had been verified 200 the same day. Only the request was wrong.
    """
    if status == 200:
        return "REACHABLE", "200"
    if status == 400:
        low = body.lower()
        if "field required" in low or "is required" in low or "required" in low:
            return "REACHABLE", "400 missing required param — endpoint exists, key accepted"
        if "not supported for this organization type" in low:
            return "ORG_TYPE_UNSUPPORTED", "400 org type — Console-vs-Enterprise, not a gap"
        return "BAD_REQUEST", f"400 {body[:70]}"
    if status == 401:
        return "WRONG_KEY_CLASS", "401 — a different key TYPE is needed, not a scope grant"
    if status == 403:
        return "WRONG_SCOPE", "403 — key class is right, scope is missing"
    if status == 404:
        return "ABSENT", "404 — absent for this org type, or wrong auth type"
    if status == 405:
        return "WRONG_VERB", "405 — path exists, verb does not"
    if status is None:
        return "PROBE_FAILED", body[:70]
    return "UNEXPECTED", f"{status} {body[:60]}"


# Minimal params that make a probe a WELL-FORMED request rather than an
# incomplete one. Three different date-param families across one vendor API
# (engagement `date`, summaries `starting_date`, cost/usage `starting_at`) — and
# engagement has a ~3-day freshness floor, so "today" is refused. Learned the
# expensive way: mcp-infra #718, where a poller asked inside the floor and
# 400-looped 12x/hour for four days.
PROBE_PARAMS = {
    "starting_at": ("starting_at", 3),
    "starting_date": ("starting_date", 5),
    "date": ("date", 5),
}


def probe_params_for(path: str) -> dict[str, str]:
    """Pick the right date-param family for this endpoint, floor-aware."""
    import datetime
    engagement = ("/analytics/skills", "/analytics/connectors", "/analytics/plugins",
                  "/analytics/artifacts", "/analytics/users", "/analytics/apps/chat/projects")
    if path.endswith("/analytics/summaries"):
        name, back = PROBE_PARAMS["starting_date"]
    elif any(path.endswith(e) for e in engagement):
        name, back = PROBE_PARAMS["date"]
    elif "report" in path:
        name, back = PROBE_PARAMS["starting_at"]
    else:
        return {}
    d = datetime.date.today() - datetime.timedelta(days=back)
    # No `limit`: /analytics/summaries REJECTS it ("limit: Extra inputs are not
    # permitted"), which a probe would otherwise report as a permanent 400 —
    # an endpoint made to look unreachable by the probe's own extra param.
    # The date param alone is enough to make the request well-formed.
    if name == "starting_at":
        return {name: d.isoformat() + "T00:00:00Z"}
    return {name: d.isoformat()}


def probe_endpoint(path: str, key: str, method: str = "GET") -> tuple[int | None, str]:
    """One read-only reachability probe. Returns (status, short_note).

    Status semantics (from the endpoint-registry's error table — these are NOT
    interchangeable, and reading them loosely is what produced three wrong
    coverage gradings on 2026-07-28):
      200 reachable · 401 wrong key CLASS · 403 wrong SCOPE
      404 wrong auth type OR absent for this org type · 405 wrong verb/path
      400 'not supported for this organization type' = Console-vs-Enterprise
    """
    if method.upper() not in PROBE_SAFE_METHODS:
        raise UnsafeProbe(
            f"refusing to probe {method} {path}: only {sorted(PROBE_SAFE_METHODS)} are "
            f"probe-safe. A DELETE endpoint's existence is verified from the doc "
            f"declaration, never by calling it — the compliance API's 5 DELETEs act on "
            f"production chats/projects/documents."
        )
    import urllib.error
    import urllib.parse
    import urllib.request
    params = probe_params_for(path)
    url = f"https://api.anthropic.com{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, classify_probe(r.status, "")[1]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return e.code, classify_probe(e.code, body)[1]
    except Exception as exc:  # noqa: BLE001 — transient, reported not raised
        return None, classify_probe(None, f"{type(exc).__name__}: {exc}")[1]


def collect_probes(kb: Path) -> dict[str, dict]:
    """Reachability for the probe-able channels. Missing key = SKIPPED, never a gap.

    A missing credential must not read as "endpoint unreachable" — that conflates
    an instrument problem with a finding, the exact class this skill exists to
    keep separate.
    """
    out: dict[str, dict] = {}
    for base_key, (key_class, explicit) in PROBE_ENDPOINTS.items():
        api_key = keychain(KEY_SERVICES[key_class])
        paths = explicit if explicit is not None else (load_baseline(kb, base_key) or [])
        if not api_key:
            out[base_key] = {"status": "SKIPPED_NO_KEY",
                            "key_service": KEY_SERVICES[key_class],
                            "paths": len(paths)}
            continue
        results = {}
        for p in paths:
            if "{" in p:      # a templated path needs a real id; not probe-able
                results[p] = [None, "templated — needs a concrete id, not probed"]
                continue
            st, note = probe_endpoint(p, api_key)
            results[p] = [st, note]
        # Count by VERDICT, not by literal 200. A 400-missing-param endpoint IS
        # reachable; counting only 200s reported 0/11 analytics unreachable on the
        # first run when all 11 were verified 200 the same day.
        reachable = sum(1 for st, note in results.values()
                        if st is not None and classify_probe(st, note)[0] == "REACHABLE")
        out[base_key] = {
            "status": "PROBED",
            "key_class": key_class,
            "reachable": reachable,
            "total": len(results),
            "detail": results,
        }
    return out


def load_baseline(kb: Path, key: str) -> list[str] | None:
    p = kb / "reference" / "claude-data-channels" / "baselines" / f"{key}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    v = d.get("values", d)
    return list(v) if isinstance(v, list) else None


def write_baseline(kb: Path, key: str, values: list[str], run_date: str, source: str,
                   newly_observed: list[str] | None = None) -> None:
    p = kb / "reference" / "claude-data-channels" / "baselines" / f"{key}.json"
    existing = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    prior_values = set(existing.get("values") or [])
    existing["values"] = sorted(values)
    existing["captured"] = run_date
    # `count` is a DERIVED field — a stale one turns the baseline into a file that
    # contradicts itself (28 declared vs 29 values), and any consumer trusting it
    # reads the wrong number forever. Recompute, never carry forward.
    if "count" in existing:
        existing["count"] = len(existing["values"])
    # Provenance matters: a value that came from OUR telemetry is not a vendor
    # claim, and a future reader must be able to tell which is which. `source_url`
    # is the VENDOR page and must survive untouched — an earlier version of this
    # writer set `source`, which read as replacing that attribution. The observed
    # leg gets its own key.
    existing["observed_source"] = source

    # PER-VALUE provenance, not just the flat string above. `diff_channels.py`
    # holds out `observed_values` from its docs comparison; a value added to
    # `values` WITHOUT being listed there is reported as a phantom REMOVAL on
    # every subsequent run — reintroducing the exact bug claude-config #1864 fixed,
    # from the writer's side instead of the reader's.
    #
    # Measured 2026-08-02: this writer added 5 values (design_project_sharing_updated
    # + 4 cc-analytics tool fields) to `values` and left `observed_values` untouched,
    # so all 5 were already queued to read as vendor removals.
    #
    # A value is observed-only if it is NEW here (absent from the prior `values`) or
    # already marked. Anything the docs already carried stays docs-sourced.
    added = sorted(set(existing["values"]) - prior_values) if newly_observed is None \
        else sorted(newly_observed)
    obs = sorted((set(existing.get("observed_values") or []) | set(added))
                 & set(existing["values"]))
    if obs:
        existing["observed_values"] = obs
    existing.pop("source", None)
    p.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")


# The two sides use different NAMING CONVENTIONS for the same fact, so a raw set
# difference is meaningless for some fact-sets. Docs write the fully-qualified OTel
# event (`claude_code.api_error`); Athena's `event_name` column stores the bare
# suffix (`api_error`). Without normalization the reconciler reported ALL 25
# observed events as UNDOCUMENTED and would have written 25 duplicate bare-name
# rows into the baseline plus a permanent false DRIFT — caught only because the
# count (25) implausibly equalled the whole observed set.
#
# Normalize the OBSERVED side up to the baseline's convention, never the reverse:
# the baseline is what the differ compares against, so its form is canonical.
NORMALIZERS = {
    "otel-events": lambda v: v if v.startswith("claude_code.") else f"claude_code.{v}",
}


def normalize(key: str, values: list[str]) -> list[str]:
    fn = NORMALIZERS.get(key)
    return sorted({fn(v) for v in values}) if fn else sorted(set(values))


def reconcile(kb: Path, observed: dict[str, list[str]]) -> dict:
    out = {}
    for key, raw_obs in observed.items():
        obs = normalize(key, raw_obs)
        base = load_baseline(kb, key)
        if base is None:
            out[key] = {"status": NO_BASELINE, "observed_count": len(obs)}
            continue
        undocumented = sorted(set(obs) - set(base))
        doc_only = sorted(set(base) - set(obs))
        out[key] = {
            "status": UNDOCUMENTED if undocumented else RECONCILED,
            "baseline_count": len(base),
            "observed_count": len(obs),
            "undocumented": undocumented,
            "doc_only_count": len(doc_only),
            "doc_only_sample": doc_only[:10],
        }
    return out


def render(rec: dict) -> str:
    lines = ["=" * 72, "OBSERVED-vs-DOCUMENTED RECONCILIATION", "=" * 72]
    blind = [k for k, v in rec.items() if v.get("undocumented")]
    lines.append(f"fact-sets: {len(rec)}   detector-blind: {len(blind)}")
    lines.append("")
    for key, v in sorted(rec.items()):
        lines.append(f"[{v['status']}] {key}")
        if v["status"] == NO_BASELINE:
            lines.append(f"    observed {v['observed_count']}, no baseline to compare")
            continue
        lines.append(
            f"    baseline {v['baseline_count']}  observed {v['observed_count']}  "
            f"documented-but-unobserved {v['doc_only_count']}")
        for u in v.get("undocumented", []):
            lines.append(f"    UNDOCUMENTED  {u}")
    if blind:
        lines += ["", "ACTION: add the UNDOCUMENTED values to their baselines "
                      "(--update-baseline), and consider whether each warrants a detector.",
                  "These are LIVE in our data and the docs-only differ can never see them."]
    return "\n".join(lines)


def render_probes(probes: dict) -> str:
    lines = ["=" * 72, "LIVE REACHABILITY PROBES (read-only GET; DELETE never probed)", "=" * 72]
    for key, v in sorted(probes.items()):
        if v["status"] == "SKIPPED_NO_KEY":
            lines.append(f"[SKIPPED] {key} — no key in Keychain service "
                        f"{v['key_service']} ({v['paths']} paths unprobed)")
            lines.append("    A missing credential is an INSTRUMENT gap, not an "
                        "unreachable endpoint. Do not read it as coverage.")
            continue
        lines.append(f"[PROBED] {key} — {v['reachable']}/{v['total']} returned 200 "
                    f"(key class: {v['key_class']})")
        for path, (st, note) in sorted(v["detail"].items()):
            if st != 200:
                lines.append(f"    {st!s:>4}  {path}  — {note}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", required=True, type=Path)
    ap.add_argument("--observed", type=Path, help="pre-computed observed inventory JSON")
    ap.add_argument("--profile", default="dev-security")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--run-date", default="")
    ap.add_argument("--probe", action="store_true",
                    help="also run read-only reachability probes (GET only; never DELETE)")
    ap.add_argument("--probe-only", action="store_true",
                    help="skip Athena; run only the reachability probes")
    ap.add_argument("--timeout", type=int, default=DEFAULT_ATHENA_TIMEOUT_S,
                    help=f"shared Athena poll budget in seconds for the whole batch "
                         f"(default {DEFAULT_ATHENA_TIMEOUT_S}; raise it when the scan grows)")
    ap.add_argument("--save-observed", type=Path,
                    help="write the collected observed inventory here, for a later "
                         "offline --observed re-diff (--observed is an INPUT — "
                         "run 6 passed a nonexistent path there and got a raw crash)")
    ap.add_argument("--watch", action="store_true",
                    help="also run the canned Watching checks against the lake "
                         "(desktop vocabulary rename/appearance, credential-pair "
                         "thresholds, retention-sweep health) — previously hand-run")
    ap.add_argument("--allow-stale-code", action="store_true",
                    help="proceed even if the RUNNING copy of this skill is behind "
                         "origin/main (see diff_channels.code_freshness)")
    a = ap.parse_args(argv)

    # Code-freshness gate (shared with diff_channels): run 6 executed a
    # 143-commit-stale checkout and died on the exact Athena budget this file
    # had already fixed upstream. Offline --observed re-diffs are exempt: they
    # touch no instrument that staleness can corrupt beyond the diff itself.
    if not a.observed:
        try:
            from diff_channels import code_freshness
            status, detail = code_freshness()
            if status == "STALE" and not a.allow_stale_code:
                print(f"[CODE_STALE] {detail}", file=sys.stderr)
                print("refusing to run stale instruments; re-run from an origin/main "
                      "worktree, or pass --allow-stale-code", file=sys.stderr)
                return 2
            if status != "FRESH":
                print(f"[CODE_{status}] {detail}", file=sys.stderr)
        except ImportError:
            print("[CODE_UNKNOWN] diff_channels not importable — code currency "
                  "unchecked", file=sys.stderr)

    probes: dict[str, dict] = {}
    if a.probe or a.probe_only:
        probes = collect_probes(a.kb)

    if a.probe_only:
        print(render_probes(probes))
        if a.json:
            a.json.write_text(json.dumps({"probes": probes}, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
        return 0

    watch_report: dict = {}
    watch_alarm = False
    if a.watch:
        try:
            watch_report, watch_alarm = run_watch(a.kb, a.profile, a.timeout)
        except RuntimeError as exc:
            print(f"INSTRUMENT PROBLEM (watch): {exc}", file=sys.stderr)
            return 2

    if a.observed:
        if not a.observed.exists():
            print(f"ERROR: --observed {a.observed} does not exist. --observed READS a "
                  f"previously collected inventory; to produce one, run without "
                  f"--observed and pass --save-observed <path>.", file=sys.stderr)
            return 2
        observed = json.loads(a.observed.read_text(encoding="utf-8"))
    else:
        try:
            observed = collect_observed(a.profile, a.timeout)
        except RuntimeError as exc:
            print(f"INSTRUMENT PROBLEM: {exc}", file=sys.stderr)
            return 2
        if a.save_observed:
            a.save_observed.write_text(
                json.dumps(observed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"observed inventory saved to: {a.save_observed}", file=sys.stderr)

    rec = reconcile(a.kb, observed)
    print(render(rec))
    if watch_report:
        print()
        print(render_watch(watch_report, watch_alarm))
    if probes:
        print()
        print(render_probes(probes))
    if a.json:
        a.json.write_text(
            json.dumps({"reconciliation": rec, "probes": probes,
                        "watch": watch_report}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")

    if a.update_baseline:
        for key, v in rec.items():
            if v.get("undocumented"):
                base = load_baseline(a.kb, key) or []
                merged = sorted(set(base) | set(normalize(key, observed[key])))
                write_baseline(a.kb, key, merged, a.run_date or "unknown",
                               "docs + live-observed reconciliation")
                print(f"  baseline updated: {key} -> {len(merged)} values")
        return 1 if watch_alarm else 0

    if any(v.get("undocumented") for v in rec.values()) or watch_alarm:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
