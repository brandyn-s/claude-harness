#!/usr/bin/env python3
"""Live A/B runner for the gather-claude efficacy harness (harness/PROBLEM.md).

REQUIRES KEYS — run MANUALLY, never in CI. Refreshing results.json is a manual
keyed run of this script. CI asserts on the committed results.json only.

That committed file is the frozen 2026-05-31 Opus 4.8 baseline. New runs
require an explicit historical/current mode and a non-frozen output path.

What it does
------------
For each fixture claim, runs TWO arms on the SAME explicitly selected model
(historical reproduction uses claude-opus-4-8) with the SAME web_search tool — the ONLY
difference is the system prompt:
  * WITH  = the gather-claude first-party-source + version-awareness verdict
            framework (the thing under test).
  * BASE  = a strong, plain expert single pass, no framework (fair baseline).
Each arm returns {verdict, cited_urls, confidence}. For every SUPPORTED verdict
the runner fetches the arm's OWN cited URL over plain HTTP (no key) and applies
the deterministic term-overlap grounding check in grade.py. Repeats N>=3 runs,
aggregates mean+spread, writes results.json and raw transcripts under runs/.

Anti-circularity: the producer (Opus) NEVER judges its own output. Scoring is
hand-labels (verdict correctness) + deterministic HTTP grounding (grade.py).

Usage:
    python3 skills/gather-claude/harness/run_live.py --model claude-opus-5 --output /tmp/gather-claude.json
    Add --runs 1 --limit 2 for a cheap smoke, or --runs 3 --workers 5.
Env: ANTHROPIC_API_KEY (only key required).
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
# PRIMARY = verdict_accuracy (the skill's actual job: classify claims correctly).
# NOT grounding_precision: it is fetch-dependent and saturates at 1.0/1.0 for BOTH
# arms (stdev 0 across runs) -> structurally cannot discriminate (PROBLEM.md §4).
# Re-designated after the 2026-05-31 calibration fix; the choice is direction-neutral
# (verdict_accuracy-as-primary yields 'fix' on the PRE-fix metrics too, so it does not
# flatter the framework — see PROBLEM.md §6).
PRIMARY_METRIC = "verdict_accuracy"
COST_RATIO = 5.0                    # gather-claude ~ multi-phase (gh + CHANGELOG + web); ~3-6x

# ---- the only difference between the two arms: the system prompt ----

SYSTEM_WITH = """You are verifying a claim about Claude Code (Anthropic's coding CLI/agent) \
using a strict FIRST-PARTY-SOURCE and version-awareness framework. For the given claim:

1. Use the web_search tool. PRIORITIZE first-party Anthropic sources: the anthropics/claude-code \
GitHub CHANGELOG and issues/PRs, and the official docs at code.claude.com / docs.claude.com. \
Treat third-party blogs/tutorials as ADJACENT — they are frequently STALE for this fast-moving \
product, so they do not by themselves establish that something is CURRENT.
2. Be VERSION-AWARE: a feature/flag/command real in an older version may have been deprecated, \
removed, renamed, or changed. Verify the CURRENT state against the latest first-party source.
3. Assign a verdict:
   - SUPPORTED: the claim describes a CURRENT, shipped Claude Code capability. A first-party \
source (CHANGELOG / docs / issue) confirming the SPECIFIC feature is the strongest evidence — but \
absence of a first-party hit in YOUR bounded search is NOT proof the feature is uncharted. If \
multiple independent credible sources describe the SAME specific feature/flag/command and no \
first-party source CONTRADICTS it, mark SUPPORTED at MEDIUM/LOW confidence rather than downgrading \
a genuinely-current feature to UNCHARTED.
   - OUTDATED: it was true once but is now deprecated / removed / renamed / changed (cite the \
first-party deprecation or breaking-change note).
   - REFUTED: first-party sources contradict the behavior the claim asserts.
   - UNCHARTED: NO credible source — first-party OR third-party — attests the SPECIFIC named \
feature exists. Reserve this for features with no real attestation anywhere: a SINGLE plausible \
mention, or a DIFFERENT feature with a similar name, still counts as no attestation and stays \
UNCHARTED. Do NOT mark a feature UNCHARTED merely because your bounded search missed a first-party \
page (absence of evidence in a search is a property of the search, not the world).
4. Only cite a URL as support if the page actually documents the SPECIFIC feature/command/field \
named in the claim — not a merely adjacent feature.

Output ONLY a final fenced ```json block: {"verdict": "<SUPPORTED|REFUTED|CONTESTED|OUTDATED|UNCHARTED>", \
"cited_urls": ["..."], "confidence": "<HIGH|MEDIUM|LOW>"}. cited_urls = the real first-party URLs you \
found that bear on the claim (empty list if UNCHARTED)."""

SYSTEM_BASE = """You are an expert on developer tools and CLIs. For the given claim about Claude \
Code (Anthropic's coding CLI/agent), determine whether it is true and current. Use the web_search \
tool to look it up, and cite the sources you rely on.

Output ONLY a final fenced ```json block. The verdict MUST be exactly one of: \
TRUE (current/shipped) | FALSE (claim is wrong) | DEPRECATED | OUTDATED | NONEXISTENT \
(no such feature). {"verdict": "<TRUE|FALSE|DEPRECATED|OUTDATED|NONEXISTENT>", \
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
            model=MODEL, max_tokens=2000,
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
        r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 (gather-claude-grounding-check)"},
                      follow_redirects=True, timeout=25)
        if r.status_code == 200:
            txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))
    except Exception:
        txt = ""
    _FETCH_CACHE[url] = txt
    return txt


def _ground(claim_obj: dict, verdict_obj: dict) -> bool | None:
    """Grounded iff a SUPPORTED verdict cites a URL whose fetched text passes the term check."""
    if grade.normalize_verdict(verdict_obj["verdict"]) != "supported":
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
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
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
        json.dumps({"runs": transcripts}, indent=2), encoding="utf-8")

    agg = {arm: grade.aggregate_runs(runs) for arm, runs in per_arm_runs.items()}
    # Phase B: annotate the with-skill aggregate with a paired-bootstrap CI vs baseline
    # so decide_verdict can apply the CI-aware rule (no-op if stats unavailable).
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


def main(argv=None):
    global MODEL, RESULTS, RUN_RECEIPT
    ap = argparse.ArgumentParser(description="gather-claude live efficacy A/B")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--historical-reproduction", action="store_true")
    mode.add_argument("--model", help="explicit current-model id")
    ap.add_argument("--approve-covered-model-retention", action="store_true",
                    help="acknowledge mandatory 30-day retention for Fable/Mythos")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--runs", type=int, default=8)
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
                   "requested_model": model, "qualification_status": "UNVERIFIED",
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
    MODEL, RESULTS = model, output
    with RUNTIME_LOCK:
        RUNTIME_OBSERVATIONS.clear()
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
