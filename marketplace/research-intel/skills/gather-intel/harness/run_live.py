#!/usr/bin/env python3
"""Live A/B runner for the gather-intel efficacy harness (harness/PROBLEM.md).

REQUIRES KEYS — run MANUALLY, never in CI. Refreshing results.json is a manual
keyed run of this script. CI asserts on the committed results.json only.

That committed file is the frozen 2026-05-31 Opus 4.8 baseline. New runs
require an explicit historical/current mode and a non-frozen output path.

What it does
------------
For each fixture claim, runs TWO arms on the SAME explicitly selected model
(historical reproduction uses claude-opus-4-8) with the SAME web_search tool — the ONLY
difference is the system prompt:
  * WITH  = the gather-intel source-authority + adversarial community-intel
            framework (the thing under test).
  * BASE  = a strong, plain expert single pass, no framework (fair baseline).
Each arm returns {verdict, cited_urls, confidence}. For every SUPPORTED verdict
the runner fetches the arm's OWN cited URL over plain HTTP (no key) and applies
the deterministic term-overlap grounding check in grade.py. Repeats N>=3 runs,
aggregates mean+spread, writes results.json and raw transcripts under runs/.

Anti-circularity: the producer (Opus) NEVER judges its own output. Scoring is
hand-labels (verdict correctness) + deterministic HTTP grounding (grade.py).

Usage:
    python3 skills/gather-intel/harness/run_live.py --model claude-opus-5 --output /tmp/gather-intel.json
    Add --runs 1 --limit 2 for a cheap smoke, or --runs 3 --workers 5.
Env: ANTHROPIC_API_KEY (only key required). Deps: anthropic, httpx, pyyaml.

Refreshing the committed sample (see harness/README.md for the full procedure):
this script writes runs/transcripts-<ts>.json as a top-level LIST of
{"run_idx": N, "records": [...]}, gitignored. The committed, re-gradeable
runs/sample-records-<date>.json the test suite reads is a DICT:
{"runs": [<same run objects>]}. Wrap the transcripts list under a "runs" key
(dropping each record's "_text" field keeps the sample compact) and save as
runs/sample-records-<date>.json, e.g.:
    python3 -c "
    import json
    t = json.load(open('harness/runs/transcripts-<ts>.json'))
    runs = [{'run_idx': r['run_idx'],
             'records': [{k: v for k, v in rec.items() if k != '_text'}
                         for rec in r['records']]}
            for r in t]
    json.dump({'runs': runs}, open('harness/runs/sample-records-<date>.json', 'w'),
              indent=2)
    "
Delete the superseded sample-records-*.json and update EXPECTED_VERDICT +
SKILL.md (and PROBLEM.md's frozen-baseline table) if the verdict changed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from threading import Lock

HARNESS = Path(__file__).resolve().parent
sys.path.insert(0, str(HARNESS))
import grade  # type: ignore  # noqa: E402

FIXTURE = HARNESS / "fixture.json"
FROZEN_RESULTS = HARNESS / "results.json"
RESULTS = FROZEN_RESULTS
RUNS_DIR = HARNESS / "runs"

HISTORICAL_MODEL = "claude-opus-4-8"
COVERED_MODELS = {"claude-fable-5", "claude-mythos-5"}
VALID_TERMINAL_STOPS = {"end_turn"}
MODEL: str | None = None
RUN_RECEIPT: dict = {}
RUNTIME_OBSERVATIONS: list[dict] = []
RUNTIME_LOCK = Lock()
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}
PRIMARY_METRIC = "grounding_precision"
COST_RATIO = 5.0                    # gather-intel ~ multi-wave community search + adversarial; ~3-6x

# ---- the only difference between the two arms: the system prompt ----

SYSTEM_WITH = """You are assessing a claim about the Claude Code COMMUNITY (third-party tools, \
repos, patterns, and practitioner consensus) using a strict SOURCE-AUTHORITY + adversarial \
framework. For the given claim:

1. Use the web_search tool to find real community sources (GitHub repos, npm, Reddit/HN, \
practitioner blogs). Score each source's AUTHORITY: T1 official Anthropic / well-known \
practitioner / widely-starred repo; ... T5 anonymous, unverified, single low-signal mention.
2. Run an ADVERSARIAL check: actively search for counter-evidence, "doesn't work", deprecation, \
or contradicting practitioner reports before accepting a claim.
3. Be VERSION-AWARE: community workarounds for old Claude Code bugs are frequently STALE — if the \
platform fixed/changed the underlying behavior, the community workaround is OUTDATED.
4. Assign a verdict:
   - SUPPORTED: a REAL, CURRENT community tool/pattern, backed by a credible (>=T2) source.
   - OUTDATED: a community workaround/claim that was valid once but the platform has obsoleted.
   - REFUTED: credible sources contradict the claim (it is false, or an over-generalized/over-\
claimed statistic, or falsely attributes official status).
   - UNCHARTED: no credible source establishes the named tool/standard/benchmark exists. Do NOT \
manufacture support from a plausible name alone or from a hype claim with no backing.
5. Only cite a URL as support if the page actually documents the SPECIFIC tool/claim named.

Output ONLY a final fenced ```json block: {"verdict": "<SUPPORTED|REFUTED|CONTESTED|OUTDATED|UNCHARTED>", \
"cited_urls": ["..."], "confidence": "<HIGH|MEDIUM|LOW>"}. cited_urls = the real community URLs you \
found (empty list if UNCHARTED)."""

SYSTEM_BASE = """You are an expert on developer-tool communities. For the given claim about the \
Claude Code community (third-party tools, repos, patterns, practitioner consensus), determine \
whether it is true and current. Use the web_search tool to look it up, and cite your sources.

Output ONLY a final fenced ```json block. The verdict MUST be exactly one of: \
TRUE (real/current) | FALSE (claim is wrong) | OUTDATED (was true, now stale) | NONEXISTENT \
(no such tool/standard). {"verdict": "<TRUE|FALSE|OUTDATED|NONEXISTENT>", \
"cited_urls": ["..."], "confidence": "<HIGH|MEDIUM|LOW>"}."""

ARMS = {"with_skill": SYSTEM_WITH, "baseline": SYSTEM_BASE}

USER_TMPL = "Claim to assess:\n\n\"{claim}\"\n\nResearch it and return your JSON verdict."

_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_OBJ = re.compile(r"\{[^{}]*\"verdict\"[^{}]*\}", re.DOTALL)


class RuntimeQualificationError(RuntimeError):
    """Provider evidence did not qualify the requested model run."""


def _record_runtime_response(message, *, terminal: bool = True) -> None:
    effective_model = getattr(message, "model", None)
    stop_reason = getattr(message, "stop_reason", None)
    content_types = [getattr(block, "type", None) for block in getattr(message, "content", [])]
    refusal = stop_reason == "refusal" or "refusal" in content_types
    truncation = stop_reason == "max_tokens"
    failures: list[str] = []
    if not isinstance(effective_model, str) or not effective_model:
        failures.append("missing effective model")
    elif effective_model != MODEL:
        failures.append(f"model mismatch: requested {MODEL}, effective {effective_model}")
    if not isinstance(stop_reason, str) or not stop_reason:
        failures.append("missing stop reason")
    if refusal:
        failures.append("provider refusal detected")
    if truncation:
        failures.append("response truncation detected")
    if terminal and stop_reason not in VALID_TERMINAL_STOPS:
        failures.append(f"invalid terminal stop outcome: {stop_reason!r}")
    if not terminal and stop_reason != "pause_turn":
        failures.append(f"invalid intermediate stop outcome: {stop_reason!r}")
    with RUNTIME_LOCK:
        RUNTIME_OBSERVATIONS.append({
            "effective_model": effective_model, "stop_reason": stop_reason,
            "terminal": terminal, "refusal_detected": refusal,
            "truncation_detected": truncation, "failures": failures,
        })


def _qualified_runtime_receipt() -> dict:
    with RUNTIME_LOCK:
        observations = list(RUNTIME_OBSERVATIONS)
    if not observations:
        raise RuntimeQualificationError("runtime qualification failed: no provider responses observed")
    failures = sorted({failure for obs in observations for failure in obs["failures"]})
    if failures:
        raise RuntimeQualificationError("runtime qualification failed: " + "; ".join(failures))
    terminal_count = sum(bool(obs["terminal"]) for obs in observations)
    if not terminal_count:
        raise RuntimeQualificationError("runtime qualification failed: no terminal response observed")
    stop_outcomes: dict[str, int] = {}
    for obs in observations:
        reason = obs["stop_reason"]
        stop_outcomes[reason] = stop_outcomes.get(reason, 0) + 1
    return {**RUN_RECEIPT, "qualification_status": "QUALIFIED", "effective_model": MODEL,
            "provider": "anthropic", "refusal_detected": False,
            "truncation_detected": False, "stop_outcomes": stop_outcomes,
            "response_count": len(observations), "terminal_response_count": terminal_count}


def _extract_json(text: str) -> dict:
    """Parse the arm's final JSON verdict, robustly."""
    m = list(_JSON_BLOCK.finditer(text))
    candidates = [m[-1].group(1)] if m else []
    candidates += [x.group(0) for x in _BARE_OBJ.finditer(text)][::-1]
    for c in candidates:
        try:
            obj = json.loads(c)
            if "verdict" in obj:
                obj.setdefault("cited_urls", [])
                obj.setdefault("confidence", "")
                if isinstance(obj["cited_urls"], str):
                    obj["cited_urls"] = [obj["cited_urls"]]
                return obj
        except json.JSONDecodeError:
            continue
    return {"verdict": "PARSE_ERROR", "cited_urls": [], "confidence": "", "_raw": text[:500]}


def _call_arm(system: str, claim: str) -> tuple[dict, str]:
    """One arm, one claim. Returns (parsed_verdict, full_text). Handles pause_turn."""
    import anthropic
    client = anthropic.Anthropic()
    messages: list[dict] = [{"role": "user", "content": USER_TMPL.format(claim=claim)}]
    full_text, guard = "", 0
    while True:
        guard += 1
        # Historical Opus 4.8 rejects `temperature`; omission is safe in current mode too.
        # residual run-to-run variance is captured by N>=3 mean+spread.
        msg = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS,
            system=system, tools=[WEB_SEARCH_TOOL], messages=messages,  # type: ignore[arg-type]
        )
        stop_reason = getattr(msg, "stop_reason", None)
        _record_runtime_response(msg, terminal=stop_reason != "pause_turn" or guard >= 4)
        full_text += "".join(getattr(b, "text", "") for b in msg.content if b.type == "text")
        if stop_reason == "pause_turn" and guard < 4:
            messages.append({"role": "assistant", "content": msg.content})
            continue
        break
    return _extract_json(full_text), full_text


_FETCH_CACHE: dict[str, str] = {}


def _fetch_text(url: str) -> str:
    """Plain-HTTP GET of a cited URL, HTML stripped. No key. Cached per process."""
    if url in _FETCH_CACHE:
        return _FETCH_CACHE[url]
    import httpx
    txt = ""
    try:
        r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 (gather-research-grounding-check)"},
                      follow_redirects=True, timeout=25)
        if r.status_code == 200:
            txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))
    except Exception:
        txt = ""
    _FETCH_CACHE[url] = txt
    return txt


def _ground(claim_obj: dict, verdict_obj: dict) -> bool | None:
    """Grounded iff a SUPPORTED verdict cites a URL whose fetched text passes the term check.
    None for not-SUPPORTED verdicts and for claims the fixture marks `groundable: false`
    (no fetch: the oracle has no page-level phrase to check, so precision excludes them)."""
    if grade.normalize_verdict(verdict_obj["verdict"]) != "supported":
        return None
    if not claim_obj.get("groundable", True):
        return None
    for url in verdict_obj.get("cited_urls", []):
        if grade.grounding_passes(claim_obj["grounding_terms"], _fetch_text(url)):
            return True
    return False


def _one_task(arm: str, system: str, claim_obj: dict) -> dict:
    verdict_obj, full_text = _call_arm(system, claim_obj["claim"])
    grounded = _ground(claim_obj, verdict_obj)
    return {
        "arm": arm, "id": claim_obj["id"], "category": claim_obj["category"],
        "raw_verdict": verdict_obj["verdict"], "cited_urls": verdict_obj.get("cited_urls", []),
        "confidence": verdict_obj.get("confidence", ""), "grounded": grounded,
        "_text": full_text,
    }


def run(n_runs: int, limit: int | None, workers: int) -> dict:
    try:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"error: cannot load fixture {FIXTURE}: {e}", file=sys.stderr)
        print("hint: fixture.json must be valid JSON; restore it with "
              "`git checkout -- skills/gather-intel/harness/fixture.json` and re-run.",
              file=sys.stderr)
        sys.exit(2)
    claims = fixture["claims"][:limit] if limit else fixture["claims"]
    fixture_sha = sha256(FIXTURE.read_bytes()).hexdigest()[:12]
    RUNS_DIR.mkdir(exist_ok=True)

    per_arm_runs: dict[str, list[dict]] = {arm: [] for arm in ARMS}
    transcripts = []

    for run_idx in range(n_runs):
        tasks = [(arm, system, c) for arm, system in ARMS.items() for c in claims]
        records: list[dict] = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_one_task, arm, system, c): (arm, c["id"]) for arm, system, c in tasks}
            for fut in as_completed(futs):
                arm, cid = futs[fut]
                try:
                    records.append(fut.result())
                except Exception as e:
                    arm0 = futs[fut][0]
                    records.append({"arm": arm0, "id": cid, "raw_verdict": "CALL_ERROR",
                                    "cited_urls": [], "grounded": None, "_text": f"{type(e).__name__}: {e}"})
        for arm in ARMS:
            arm_recs = [r for r in records if r["arm"] == arm]
            per_arm_runs[arm].append(grade.score_run(fixture, arm_recs))
        transcripts.append({"run_idx": run_idx, "records": records})
        print(f"  run {run_idx+1}/{n_runs} done ({len(records)} tasks)")

    (RUNS_DIR / f"transcripts-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json").write_text(
        json.dumps(transcripts, indent=2), encoding="utf-8")

    all_records = [r for t in transcripts for r in t["records"]]
    if all_records and all(r.get("raw_verdict") == "CALL_ERROR" for r in all_records):
        print("error: every API call failed (all records are CALL_ERROR); "
              "refusing to overwrite results.json with a no-data run", file=sys.stderr)
        print("hint: check ANTHROPIC_API_KEY / network and re-run; per-call errors are "
              "in the transcripts file under harness/runs/.", file=sys.stderr)
        sys.exit(2)

    agg = {arm: grade.aggregate_runs(runs) for arm, runs in per_arm_runs.items()}
    # Phase B: attach paired-bootstrap CI vs baseline for the CI-aware verdict.
    if grade.stats is not None:
        grade.stats.attach_ci(agg["with_skill"], agg["baseline"], grade._METRIC_KEYS)
    verdict = grade.decide_verdict(agg["with_skill"], agg["baseline"], PRIMARY_METRIC,
                                   COST_RATIO, min_delta=0.05)
    runtime_receipt = _qualified_runtime_receipt()
    results = {
        "_about": "MEASURED live A/B output from an explicit harness mode; the committed "
                  "2026-05-31 results.json baseline remains immutable.",
        "model": runtime_receipt["effective_model"], "runtime_receipt": runtime_receipt,
        "arms": "with_skill (framework) vs baseline (plain strong pass)",
        "run_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "n_runs": n_runs, "n_claims": len(claims), "fixture_sha": fixture_sha,
        "primary_metric": PRIMARY_METRIC, "cost_ratio": COST_RATIO,
        "metrics": agg, "verdict": verdict,
        "per_category_n": _category_counts(claims),
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "with_skill": agg["with_skill"],
                      "baseline": agg["baseline"]}, indent=2))
    return results


def _category_counts(claims):
    out: dict = {}
    for c in claims:
        out[c["category"]] = out.get(c["category"], 0) + 1
    return out


MAX_TOKENS = 2000  # per-call output budget, applied to BOTH arms; --max-tokens overrides


def main(argv=None):
    global MODEL, RESULTS, RUN_RECEIPT, MAX_TOKENS
    ap = argparse.ArgumentParser(description="gather-intel live efficacy A/B")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--historical-reproduction", action="store_true")
    mode.add_argument("--model", help="explicit current-model id")
    ap.add_argument("--approve-covered-model-retention", action="store_true",
                    help="acknowledge mandatory 30-day retention for Fable/Mythos")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS,
                    help="per-call output budget for BOTH arms (frozen baseline used 2000)")
    ap.add_argument("--limit", type=int, default=None, help="subset N claims (smoke); writes --output")
    ap.add_argument("--workers", type=int, default=5)
    args = ap.parse_args(argv)
    model = HISTORICAL_MODEL if args.historical_reproduction else args.model
    if not args.historical_reproduction and model == HISTORICAL_MODEL:
        ap.error("Opus 4.8 is historical; use --historical-reproduction")
    if not isinstance(model, str) or not re.fullmatch(r"claude-[a-z0-9-]+", model):
        ap.error("--model must be an explicit Claude model id")
    if model in COVERED_MODELS and not args.approve_covered_model_retention:
        ap.error("Fable 5 and Mythos 5 require explicit approval of mandatory 30-day retention")
    output = args.output.expanduser().resolve()
    if output == FROZEN_RESULTS.resolve():
        ap.error("the frozen 2026-05-31 results.json is immutable")
    RUN_RECEIPT = {"mode": "historical_reproduction" if args.historical_reproduction else "current_model",
                   "requested_model": model, "max_tokens": args.max_tokens, "qualification_status": "UNVERIFIED",
                   "effective_model": "<unavailable>", "provider": "<unavailable>",
                   "refusal_detected": "<unavailable>", "truncation_detected": "<unavailable>",
                   "stop_outcomes": "<unavailable>",
                   "covered_model_retention_required": model in COVERED_MODELS,
                   "covered_model_retention_approved": model in COVERED_MODELS and args.approve_covered_model_retention,
                   "output_path": str(output),
                   "frozen_baseline": {"date": "2026-05-31", "model": HISTORICAL_MODEL,
                                       "sha256": sha256(FROZEN_RESULTS.read_bytes()).hexdigest()}}
    if args.plan_only:
        print(json.dumps(RUN_RECEIPT, indent=2))
        return 0
    MODEL, RESULTS, MAX_TOKENS = model, output, args.max_tokens
    with RUNTIME_LOCK:
        RUNTIME_OBSERVATIONS.clear()
    try:
        import httpx  # noqa: F401  # grounding fetches; anthropic>=1.3 no longer pulls it in
    except ImportError:
        print("error: httpx not importable; the grounding step needs it, and without it every "
              "SUPPORTED verdict is recorded as CALL_ERROR after the model call has been paid for",
              file=sys.stderr)
        print("hint: uv run --with anthropic --with httpx --with pyyaml python3 run_live.py ...",
              file=sys.stderr)
        return 2
    t0 = time.time()
    try:
        run(args.runs, args.limit, args.workers)
    except RuntimeQualificationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"  elapsed {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
