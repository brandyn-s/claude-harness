#!/usr/bin/env python3
"""Reconcile the OpenAI baselines against LIVE reachability and observed inventory.

The docs differ (diff_openai_channels.py) asks the vendor's public pages; this
script asks the live APIs and (optionally) our own monitor's inventory — the
only sources that can reveal a surface the docs omit. It is the OpenAI
counterpart of gather-claude-endpoints/scripts/reconcile_observed.py, with the
Athena leg replaced by (a) a bounded keyed probe set and (b) a generic
--observed JSON input extracted from the OpenAI Monitor pipeline.

Probe leg (--probe):
  - GET only, limit=1, ~12 requests total. probe_endpoint() raises UnsafeProbe
    on any non-GET method; no mutating endpoint is in any probe set.
  - Keys come from the macOS Keychain under their CURRENT names (renamed
    2026-08-04; see memory openai-keychain-items):
      OPENAI_PLATFORM_ADMIN_API -> api.openai.com   (audit_logs, users, ...)
      OPENAI_CHATGPT_ADMIN_API  -> api.chatgpt.com  (compliance logs)
      OPENAI_ORG_ID / OPENAI_WORKSPACE_ID -> principal ids (not secrets)
    A missing item reports SKIPPED_NO_KEY — an instrument gap, never
    "unreachable". Never guess service names; two guessed names once produced
    a false BLOCKED verdict on the Anthropic side.
  - A 400 "required" is REACHABLE (the request was incomplete, not the
    endpoint absent); 401 = wrong key CLASS; 403 = missing scope; 404 = absent.
  - The full key-by-endpoint matrix instrument is
    ~/Documents/projects/claude-spend-report/probe_openai_keys.py — this
    script deliberately probes only the drift-relevant subset.

Observed leg (--observed FILE):
  JSON of {"<baseline-key>": ["value", ...]} — e.g. the event types the OpenAI
  Monitor actually ingested. Verdicts per value, mirroring the sibling:
    UNDOCUMENTED  live in our data, absent from the baseline -> detector blind
    DOC_ONLY      documented, never observed -> informational, NOT a gap
    RECONCILED    observed subset of baseline -> nothing to do
  --update-baseline merges UNDOCUMENTED values with observed_values provenance.

Exit codes: 0 = reconciled/informational only; 1 = UNDOCUMENTED found;
2 = instrument problem (all probes skipped, bad input, unsafe probe).
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

USER_AGENT = "example-gather-openai-endpoints/1.0 (+internal drift reconciler)"
TIMEOUT = 30

KEY_SERVICES = {
    "platform": "OPENAI_PLATFORM_ADMIN_API",
    "chatgpt": "OPENAI_CHATGPT_ADMIN_API",
    "org_id": "OPENAI_ORG_ID",
    "workspace_id": "OPENAI_WORKSPACE_ID",
}

# Known-valid compliance event types BY SCOPE (event types are scope-bound —
# the org path rejects workspace-scoped names with a 400 naming the redirect).
# Workspace: 7 probe-discovered 2026-08-04 + CONVERSATION_MESSAGE (spec-listed,
# probed 200-with-data 2026-08-22 — the suffix-less name the 2026-08-04
# guesses missed). Org: spec-listed, probed 200 on 2026-08-22 (COSTS carried
# data). The authoritative spec's enums end in a literal "etc..." placeholder,
# so this list is known-valid, not exhaustive.
KNOWN_EVENT_TYPES = [
    "AUTH_LOG", "AUDIT_LOG", "APP_LOG", "APP_AUTH_LOG",
    "CODEX_LOG", "CODEX_SECURITY_LOG", "CUSTOM_AGENTS_LOG",
    "CONVERSATION_MESSAGE",
]
ORG_EVENT_TYPES = ["COSTS", "APP_LOG", "APP_AUTH_LOG"]


class UnsafeProbe(RuntimeError):
    """Raised when something asks to probe a non-GET endpoint. Never caught."""


def keychain(service: str) -> str | None:
    try:
        p = subprocess.run(["security", "find-generic-password", "-s", service, "-w"],
                           capture_output=True, text=True)
    except OSError:  # non-macOS host: no `security` binary -> SKIPPED_NO_KEY
        return None
    return p.stdout.strip() or None if p.returncode == 0 else None


def classify_probe(status: int | None, body: str) -> tuple[str, str]:
    """HTTP status -> reachability verdict. A 400 'required' is REACHABLE."""
    if status == 200:
        return "REACHABLE", "200"
    if status == 400:
        low = body.lower()
        if "required" in low:
            return "REACHABLE", "400 missing required param — endpoint exists, key accepted"
        if "invalid event_type" in low:
            return "INVALID_VALUE", f"400 {body[:70]}"
        return "BAD_REQUEST", f"400 {body[:70]}"
    if status == 422:
        # FastAPI-style validation (the api.chatgpt.com compliance surface uses
        # 422 where api.openai.com uses 400). A missing-required-param 422 means
        # the endpoint exists, the key was accepted, AND the supplied enum
        # values validated — REACHABLE evidence, measured live 2026-08-22.
        if '"missing"' in body or "field required" in body.lower():
            return "REACHABLE", "422 missing required param — endpoint exists, key accepted"
        return "BAD_REQUEST", f"422 {body[:70]}"
    if status == 401:
        return "WRONG_KEY_CLASS", "401 — a different key TYPE is needed"
    if status == 403:
        return "WRONG_SCOPE", "403 — key class right, scope missing"
    if status == 404:
        return "ABSENT", "404 — absent for this principal, or wrong path"
    if status == 429:
        return "RATE_LIMITED", "429 — retry later; not a reachability verdict"
    if status is None:
        return "PROBE_FAILED", body[:70]
    return "UNEXPECTED", f"{status} {body[:60]}"


def probe_endpoint(url: str, key: str, method: str = "GET") -> tuple[int | None, str]:
    if method != "GET":
        raise UnsafeProbe(f"refusing non-GET probe: {method} {url}")
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.status, resp.read(2048).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(2048).decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 — transient class, reported not raised
        return None, f"{type(exc).__name__}: {exc}"


def epoch_days_back(days: int) -> int:
    return int((datetime.datetime.now(tz=datetime.timezone.utc)
                - datetime.timedelta(days=days)).timestamp())


def platform_probe_set() -> list[tuple[str, str]]:
    """(label, path) — the Platform Admin surfaces the drift channels track.

    costs/usage take epoch start_time; the rest take only limit. limit=1
    everywhere: reachability is the question, not data volume.
    """
    t = epoch_days_back(7)
    return [
        ("audit_logs", "/v1/organization/audit_logs?limit=1"),
        ("users", "/v1/organization/users?limit=1"),
        ("projects", "/v1/organization/projects?limit=1"),
        ("invites", "/v1/organization/invites?limit=1"),
        ("admin_api_keys", "/v1/organization/admin_api_keys?limit=1"),
        ("costs", f"/v1/organization/costs?start_time={t}&limit=1"),
        ("usage_completions", f"/v1/organization/usage/completions?start_time={t}&limit=1"),
    ]


def run_probes(event_types: list[str]) -> dict:
    out: dict = {}
    platform_key = keychain(KEY_SERVICES["platform"])
    chatgpt_key = keychain(KEY_SERVICES["chatgpt"])
    org_id = keychain(KEY_SERVICES["org_id"])
    ws_id = keychain(KEY_SERVICES["workspace_id"])

    if platform_key is None:
        out["platform"] = {"status": "SKIPPED_NO_KEY",
                           "detail": f"Keychain item {KEY_SERVICES['platform']} absent"}
    else:
        plat: dict = {}
        for label, path in platform_probe_set():
            st, body = probe_endpoint(f"https://api.openai.com{path}", platform_key)
            verdict, why = classify_probe(st, body)
            plat[label] = {"status": verdict, "detail": why}
        out["platform"] = plat

    if chatgpt_key is None or (ws_id is None and org_id is None):
        missing = [KEY_SERVICES["chatgpt"]] if chatgpt_key is None else []
        missing += [KEY_SERVICES["workspace_id"], KEY_SERVICES["org_id"]] if not (ws_id or org_id) else []
        out["compliance"] = {"status": "SKIPPED_NO_KEY",
                             "detail": f"Keychain item(s) absent: {missing}"}
    else:
        comp: dict = {}
        base = "https://api.chatgpt.com/v1/compliance"
        # `after` is REQUIRED (422 without it, measured 2026-08-22); ISO8601 with tz.
        after = (datetime.datetime.now(tz=datetime.timezone.utc)
                 - datetime.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if ws_id:
            for et in event_types:
                st, body = probe_endpoint(
                    f"{base}/workspaces/{ws_id}/logs?event_type={et}&limit=1&after={after}",
                    chatgpt_key)
                verdict, why = classify_probe(st, body)
                comp[f"workspaces:{et}"] = {"status": verdict, "detail": why}
        if org_id:
            # Org-scoped types (spec-listed). A workspace-scoped name here 400s
            # with an explicit "workspace-scoped ... use /workspaces/" message.
            for et in ORG_EVENT_TYPES:
                st, body = probe_endpoint(
                    f"{base}/organizations/{org_id}/logs?event_type={et}&limit=1&after={after}",
                    chatgpt_key)
                verdict, why = classify_probe(st, body)
                comp[f"organizations:{et}"] = {"status": verdict, "detail": why}
        out["compliance"] = comp
    return out


def baseline_path(kb: Path, key: str) -> Path:
    return kb / "reference" / "openai-data-channels" / "baselines" / f"{key}.json"


def reconcile_observed(kb: Path, observed: dict[str, list[str]], update: bool) -> dict:
    """Diff observed inventory against baselines; optionally merge with provenance."""
    report: dict = {}
    for bkey, values in observed.items():
        p = baseline_path(kb, bkey)
        if not p.exists():
            report[bkey] = {"status": "NO_BASELINE", "observed_count": len(values)}
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        base = set(data.get("values", []))
        obs = set(values)
        undocumented = sorted(obs - base)
        doc_only = sorted(base - obs)
        status = "UNDOCUMENTED" if undocumented else ("RECONCILED" if not doc_only else "DOC_ONLY")
        report[bkey] = {"status": status, "undocumented": undocumented,
                        "doc_only_count": len(doc_only)}
        if update and undocumented:
            prior_obs = set(data.get("observed_values", []))
            data["values"] = sorted(base | obs)
            data["count"] = len(data["values"])
            data["observed_values"] = sorted(prior_obs | set(undocumented))
            data.setdefault("observed_source", "reconcile_openai_observed.py")
            p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                         encoding="utf-8")
            report[bkey]["merged"] = True
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kb", default=str(Path.home() / "Documents" / "knowledge-base"))
    ap.add_argument("--probe", action="store_true", help="run the live keyed probe set")
    ap.add_argument("--event-types", nargs="*", default=KNOWN_EVENT_TYPES,
                    help="compliance event types to probe (default: the known enum)")
    ap.add_argument("--observed", default=None,
                    help="JSON file {'<baseline-key>': [values]} from the monitor inventory")
    ap.add_argument("--update-baseline", action="store_true",
                    help="merge UNDOCUMENTED observed values with provenance")
    ap.add_argument("--json", default=None, help="write machine-readable results here")
    args = ap.parse_args()

    if not args.probe and not args.observed:
        print("nothing to do: pass --probe and/or --observed FILE", file=sys.stderr)
        return 2

    result: dict = {}
    rc = 0

    if args.probe:
        result["probes"] = run_probes(args.event_types)
        skipped = [k for k, v in result["probes"].items()
                   if isinstance(v, dict) and v.get("status") == "SKIPPED_NO_KEY"]
        if len(skipped) == len(result["probes"]):
            print("all probe legs skipped (no keys) — instrument gap", file=sys.stderr)
            rc = 2

    if args.observed:
        observed = json.loads(Path(args.observed).expanduser().read_text(encoding="utf-8"))
        if not isinstance(observed, dict):
            print("--observed must be a JSON object of baseline-key -> [values]",
                  file=sys.stderr)
            return 2
        kb = Path(args.kb).expanduser()
        result["reconcile"] = reconcile_observed(kb, observed, args.update_baseline)
        if any(v.get("status") == "UNDOCUMENTED" for v in result["reconcile"].values()):
            rc = max(rc, 1)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    if args.json:
        Path(args.json).expanduser().write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
