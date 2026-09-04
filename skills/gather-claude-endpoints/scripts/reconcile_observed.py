#!/usr/bin/env python3
"""Reconcile the docs-derived baselines against what a deployment ACTUALLY observes.

WHY THIS EXISTS — the docs-only blind spot.

`diff_channels.py` asks exactly one source: Anthropic's documentation. That makes
it structurally incapable of finding a surface the docs OMIT. It is a FILTER over
vendor prose, and a filter can only ever return a subset of what it was pointed
at (the enumerate-and-subtract lesson, applied to the detector itself).

Measured 2026-07-28 — the gap this closes:
  * 24 activity types were LIVE in a Compliance feed and absent from the
    412-type baseline, incl. `claude_file_uploaded` (46,860 events, a DLP
    signal), `integration_user_connected`, `platform_agent_created`.
  * `claude_code.subagent_completed` was LIVE in OTel (7,380 events / 1,467
    sessions), absent from the 28-event baseline, and already consumed by a
    downstream report — so a vendor rename would break a live consumer with no
    DRIFT ever firing.

Neither is findable by re-reading docs, because the docs don't mention them. What
a deployment actually emits is the second authoritative source, and for "what does
this org actually emit" it is the BETTER one: docs describe the product; the
observed inventory describes us.

Two legs, either or both:

Probe leg (--probe):
  Read-only GET reachability probes against api.anthropic.com for the channels
  whose live truth is "does the endpoint answer" (admin, analytics, rate limits).
  Keys come from the macOS Keychain under their documented service names; a
  missing item reports SKIPPED_NO_KEY — an instrument gap, never "unreachable".
  probe_endpoint() raises UnsafeProbe on any non-GET method, and no compliance
  channel is in the probe set at all (its DELETEs act on production data).

Observed leg (--observed FILE):
  JSON of {"<baseline-key>": ["value", ...]} — an inventory of what the
  deployment actually emitted, produced by whatever holds that data (an OTel
  backend's distinct event names, a Compliance-feed export's distinct activity
  types, an analytics export's field names). The producer is out of scope; the
  file format is the contract, and it is what makes this script runnable and
  testable with no credentials and no network. Verdicts per fact-set:
    UNDOCUMENTED  observed, absent from the baseline -> the detector is BLIND
                  to it. Action: add to the baseline (--update-baseline) and
                  consider whether it warrants a detector.
    DOC_ONLY      documented, never observed -> informational. A type the
                  product supports but this org never generates is NOT a gap;
                  counting it as one inflates every coverage denominator.
    RECONCILED    observed set equals the baseline -> nothing to do.
    NO_BASELINE   no baseline file for that key -> establish it with the differ.
  --update-baseline merges UNDOCUMENTED values with per-value provenance
  (`observed_values`), which the docs differ holds out of its comparison.

Exit codes: 0 = reconciled/informational only; 1 = UNDOCUMENTED found;
2 = instrument problem (no leg requested, unreadable inventory, every probe leg
skipped for want of a key, stale code on the probe leg).
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UNDOCUMENTED = "UNDOCUMENTED"
DOC_ONLY = "DOC_ONLY"
RECONCILED = "RECONCILED"
NO_BASELINE = "NO_BASELINE"

#: Stamped on a baseline the observed leg has merged into. `source_url` stays
#: the VENDOR page; this key records that some values came from observed data.
OBSERVED_SOURCE = "docs + observed-inventory reconciliation"

#: A value that cannot be an identifier — a space, or implausible length — is log
#: content or a formatting artefact that leaked into an inventory, not a fact.
#: Such a value is DROPPED and COUNTED, never silently kept: writing one into a
#: baseline creates a permanent phantom that every future diff must carry.
#: Measured 2026-08-02 on a flattened OTel export: an unscoped distinct-name
#: census returned 12,431 "events" against a 29-value baseline, most of them log
#: lines ("AbsLogFile : C:\\Users\\...\\zenserver.log"); the same census bounded
#: to 15 days returned 198, none containing a space.
MAX_IDENTIFIER_LEN = 80


def looks_like_identifier(v: object) -> bool:
    return isinstance(v, str) and bool(v) and " " not in v and len(v) <= MAX_IDENTIFIER_LEN


class BadInventory(ValueError):
    """--observed input is not a readable {baseline-key: [values]} object."""


def load_observed(path: Path) -> dict[str, list]:
    """Read an inventory file. Raises BadInventory with an actionable message.

    A missing or malformed inventory must never degrade to an EMPTY observed set:
    that would mark every documented fact DOC_ONLY and hide every UNDOCUMENTED
    one, rendering an input failure as perfect reconciliation.
    """
    shape = '{"<baseline-key>": ["value", ...]}'
    if not path.exists():
        raise BadInventory(
            f"--observed {path} does not exist. --observed READS an inventory JSON of "
            f"{shape}, produced from whatever holds the deployment's observed data; "
            f"this script never collects it.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BadInventory(f"--observed {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not all(isinstance(v, list) for v in data.values()):
        raise BadInventory(f"--observed must be a JSON object of baseline-key -> [values]: {shape}")
    return data


def clean_observed(observed: dict[str, list]) -> tuple[dict[str, list[str]], dict[str, list]]:
    """Split an inventory into identifier-shaped values and the junk it carried.

    Returns (kept, dropped), both keyed by baseline key. Dropped values are for
    the caller to REPORT — a silent filter would make the observed set quietly
    partial, which is the failure this reconciliation exists to prevent, wearing
    the opposite hat.
    """
    kept: dict[str, list[str]] = {}
    dropped: dict[str, list] = {}
    for key, values in observed.items():
        kept[key] = [v for v in values if looks_like_identifier(v)]
        bad = [v for v in values if not looks_like_identifier(v)]
        if bad:
            dropped[key] = bad
    return kept, dropped


# --------------------------------------------------------------------------
# Probe leg
# --------------------------------------------------------------------------

# Channels whose live truth is a REACHABILITY probe, not a stored inventory: the
# endpoint either answers or it does not. Read-only GET, one call each.
#
# HARD RULE — never probe a DELETE. The operations fact-set enumerates 5
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
    try:
        p = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                           capture_output=True, text=True)
    except OSError:  # non-macOS host: no `security` binary -> SKIPPED_NO_KEY
        return None
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
# expensive way: a poller that asked inside the floor 400-looped 12x/hour for
# four days.
PROBE_PARAMS = {
    "starting_at": ("starting_at", 3),
    "starting_date": ("starting_date", 5),
    "date": ("date", 5),
}


def probe_params_for(path: str) -> dict[str, str]:
    """Pick the right date-param family for this endpoint, floor-aware."""
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


# --------------------------------------------------------------------------
# Observed leg
# --------------------------------------------------------------------------

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
    # Provenance matters: a value that came from observed data is not a vendor
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


# The two sides can use different NAMING CONVENTIONS for the same fact, so a raw
# set difference is meaningless for some fact-sets. Docs write the fully-qualified
# OTel event (`claude_code.api_error`); a flattened export commonly stores the bare
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
        status = UNDOCUMENTED if undocumented else (DOC_ONLY if doc_only else RECONCILED)
        out[key] = {
            "status": status,
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
        lines += ["", ("ACTION: add the UNDOCUMENTED values to their baselines "
                       "(--update-baseline), and consider whether each warrants a detector."),
                  "These are LIVE in the observed data and the docs-only differ can never see them."]
    return "\n".join(lines)


def code_is_stale(allow_stale: bool) -> bool:
    """Code-freshness gate, shared with diff_channels. True = refuse to run.

    WHY — measured 2026-08-22 (run 6): the baseline-freshness gate checked the KB
    tree, but nothing checked the code being run; a 143-commit-stale checkout
    executed run-5-era scripts and reproduced a bug already fixed upstream. The
    probe leg is the live instrument here, so it is gated. An offline --observed
    re-diff touches no instrument that staleness can corrupt beyond the diff
    itself, so it is exempt.
    """
    try:
        from diff_channels import code_freshness
    except ImportError:
        print("[CODE_UNKNOWN] diff_channels not importable — code currency unchecked",
              file=sys.stderr)
        return False
    status, detail = code_freshness()
    if status == "STALE" and not allow_stale:
        print(f"[CODE_STALE] {detail}", file=sys.stderr)
        print("refusing to run stale instruments; re-run from an origin/main worktree, "
              "or pass --allow-stale-code", file=sys.stderr)
        return True
    if status != "FRESH":
        print(f"[CODE_{status}] {detail}", file=sys.stderr)
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kb", required=True, type=Path)
    ap.add_argument("--probe", action="store_true",
                    help="run the read-only reachability probes (GET only; never DELETE)")
    ap.add_argument("--observed", type=Path,
                    help='inventory JSON {"<baseline-key>": ["value", ...]} of what the '
                         "deployment actually emitted")
    ap.add_argument("--update-baseline", action="store_true",
                    help="merge UNDOCUMENTED observed values into their baselines with "
                         "per-value provenance (observed_values)")
    ap.add_argument("--run-date", default="")
    ap.add_argument("--json", type=Path, help="write machine-readable results here")
    ap.add_argument("--allow-stale-code", action="store_true",
                    help="proceed even if the RUNNING copy of this skill is behind "
                         "origin/main (see diff_channels.code_freshness)")
    a = ap.parse_args(argv)

    if not a.probe and not a.observed:
        print("nothing to do: pass --probe and/or --observed FILE", file=sys.stderr)
        return 2

    result: dict = {}
    rc = 0

    if a.probe:
        if code_is_stale(a.allow_stale_code):
            return 2
        probes = collect_probes(a.kb)
        result["probes"] = probes
        print(render_probes(probes))
        if probes and all(v["status"] == "SKIPPED_NO_KEY" for v in probes.values()):
            print("all probe legs skipped (no keys in the Keychain) — an instrument gap, "
                  "not a coverage result", file=sys.stderr)
            rc = 2

    if a.observed:
        try:
            raw = load_observed(a.observed)
        except BadInventory as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        observed, dropped = clean_observed(raw)
        for key, bad in dropped.items():
            print(f"WARNING: {key}: dropped {len(bad)} non-identifier value(s) (log content "
                  f"or formatting artefacts, not facts); first: {str(bad[0])[:70]!r}",
                  file=sys.stderr)
        rec = reconcile(a.kb, observed)
        result["reconciliation"] = rec
        if a.probe:
            print()
        print(render(rec))
        if a.update_baseline:
            for key, v in rec.items():
                if v.get("undocumented"):
                    base = load_baseline(a.kb, key) or []
                    merged = sorted(set(base) | set(normalize(key, observed[key])))
                    write_baseline(a.kb, key, merged, a.run_date or "unknown",
                                   OBSERVED_SOURCE, newly_observed=v["undocumented"])
                    print(f"  baseline updated: {key} -> {len(merged)} values")
        elif any(v.get("undocumented") for v in rec.values()):
            rc = max(rc, 1)

    if a.json:
        a.json.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
