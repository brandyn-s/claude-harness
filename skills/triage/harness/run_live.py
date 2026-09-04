#!/usr/bin/env python3
"""Live A/B runner for the triage efficacy harness (harness/PROBLEM.md).

REQUIRES KEYS — run MANUALLY, never in CI. CI asserts only on committed results.json.

The committed results are the frozen 2026-05-31 Opus 4.8 baseline. New runs
require an explicit historical/current mode and a non-frozen output path.

Tests triage's value-prop: correct PRIORITIZATION + cross-tool CORRELATION. Both arms
receive the SAME 12 findings and output a ranking (ids best->worst) + correlation groups
(sets of ids sharing a root cause), on the explicit model (historical reproduction
uses claude-opus-4-8), with NO web_search.
The ONLY difference is the prompt:
  * WITH = the triage framework — severity scoring + explicit cross-tool root-cause
           correlation (its multi-article discipline).
  * BASE = an unstructured "rank these by priority and note any that share a root cause".
Scoring (grade.py): Spearman vs the human-curated expert ranking + correlation-group
precision/recall/F1. Producer never judges itself.

Usage: python3 skills/triage/harness/run_live.py --model claude-opus-5 --output /tmp/triage.json [--runs 3]
Env: ANTHROPIC_API_KEY only.
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
# Retired at this fixture (2026-09-04): PROBLEM.md section 9, docs/research-skills-root-cause.md
# section 7. Real runs print the notice and refuse without --acknowledge-retired-fixture;
# --plan-only never needs it.
FIXTURE_STATUS = "retired"
FIXTURE_STATUS_SINCE = "2026-09-04"
FIXTURE_STATUS_NOTICE = (
    "NOTICE: this A/B fixture is RETIRED (2026-09-04): N=3 runs of a 12-item ranking cannot "
    "resolve the 0.02 Spearman delta between the arms (run-to-run spread 0.051), and the framework "
    "arm is a two-sentence prompt, not the triage constitution. Reopening needs N>=10 and the "
    "worked example removed from SYSTEM_WITH. See harness/PROBLEM.md section 9 and "
    "docs/research-skills-root-cause.md section 7."
)
VALID_TERMINAL_STOPS = {"end_turn"}
MODEL: str | None = None
RUN_RECEIPT: dict = {}
RUNTIME_OBSERVATIONS: list[dict] = []
RUNTIME_LOCK = Lock()
COST_RATIO = 5.0  # triage's 14-article constitution + correlation pass

_SCHEMA = ('Output ONLY a fenced ```json block: {"ranking": ["<id>", ... most to least urgent, '
           'ALL ids exactly once], "groups": [["<id>","<id>"], ...]} where each group is a set of '
           'finding ids that share ONE underlying root cause (omit singletons).')

SYSTEM_WITH = ("You are a security/operations triage analyst. Apply rigorous severity scoring: rank "
               "by blast radius + reversibility + active-exposure (an active credential leak that "
               "needs rotation outranks a latency issue with a known workaround, which outranks a "
               "cosmetic/style nudge). Then do an explicit CROSS-TOOL CORRELATION pass: identify "
               "findings that share ONE underlying root cause (even if they surfaced via different "
               "symptoms/tools), so they can be fixed together. " + _SCHEMA)

SYSTEM_BASE = ("You are triaging a list of findings. Rank them by priority and note any that share a "
               "root cause. " + _SCHEMA)

ARMS = {"with_skill": SYSTEM_WITH, "baseline": SYSTEM_BASE}

_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


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


def _parse(text: str) -> dict:
    cands = [m.group(1) for m in _JSON_BLOCK.finditer(text)][::-1]
    # also try the largest brace-balanced object
    for c in cands + ([text[text.find("{"):text.rfind("}") + 1]] if "{" in text and "}" in text else []):
        try:
            obj = json.loads(c)
            if "ranking" in obj:
                obj.setdefault("groups", [])
                return obj
        except (json.JSONDecodeError, ValueError):
            continue
    return {"ranking": [], "groups": [], "_parse": "fail"}


def _one(arm: str, system: str, findings_blob: str) -> dict:
    import anthropic
    msg = anthropic.Anthropic().messages.create(
        model=MODEL, max_tokens=MAX_TOKENS, system=system,
        messages=[{"role": "user", "content": findings_blob}])
    _record_runtime_response(msg)
    text = "".join(getattr(b, "text", "") for b in msg.content if b.type == "text")
    obj = _parse(text)
    return {"arm": arm, "ranking": obj.get("ranking", []), "groups": obj.get("groups", [])}


def run(n_runs: int, workers: int) -> dict:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    blob = "FINDINGS (id: description):\n" + "\n".join(
        f"- {f['id']}: {f['finding']}" for f in fixture["findings"])
    fixture_sha = sha256(FIXTURE.read_bytes()).hexdigest()[:12]
    RUNS_DIR.mkdir(exist_ok=True)
    per_arm: dict[str, list[dict]] = {a: [] for a in ARMS}
    transcripts = []
    for ri in range(n_runs):
        recs: dict[str, dict] = {}
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_one, a, s, blob): a for a, s in ARMS.items()}
            for fut in as_completed(futs):
                a = futs[fut]
                try:
                    recs[a] = fut.result()
                except Exception as e:
                    recs[a] = {"arm": a, "ranking": [], "groups": [], "_err": str(e)}
        for a in ARMS:
            per_arm[a].append(grade.score_run(fixture, recs[a]))
        transcripts.append({"run_idx": ri, "records": list(recs.values())})
        print(f"  run {ri+1}/{n_runs} done")
    (RUNS_DIR / f"transcripts-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json").write_text(
        json.dumps({"_about": "Per-run A/B arm records (arm, ranking, groups fields). Compact sample: see sample-records-*.json.", "runs": transcripts}, indent=2), encoding="utf-8")
    runtime_receipt = _qualified_runtime_receipt()
    # Refuse to treat total failure as a measurement: if NO arm call in ANY run
    # produced a ranking (auth/SDK errors land in _err; parse failures land in
    # _parse), every metric is a meaningless 0.0 and overwriting the committed,
    # CI-asserted results.json would poison the baseline.
    all_records = [r for t in transcripts for r in t["records"]]
    if not any(r.get("ranking") for r in all_records):
        errs = sorted({r["_err"] for r in all_records if "_err" in r}) or ["no parseable ranking in any response"]
        print(f"error: all {len(all_records)} arm calls failed ({'; '.join(errs)}); "
              f"refusing to overwrite {RESULTS.name} with zeroed metrics", file=sys.stderr)
        print("hint: set ANTHROPIC_API_KEY (and pip install anthropic if missing), then re-run; "
              "the committed results.json baseline was left untouched", file=sys.stderr)
        raise SystemExit(2)
    agg = {a: grade.aggregate_runs(per_arm[a]) for a in ARMS}
    # Phase B: attach paired-bootstrap CI vs baseline for the CI-aware verdict.
    if grade.stats is not None:
        grade.stats.attach_ci(agg["with_skill"], agg["baseline"], grade._METRIC_KEYS)
    verdict = grade.decide_verdict(agg["with_skill"], agg["baseline"], min_delta=0.05)
    results = {
        "_about": "MEASURED triage A/B output from an explicit harness mode; the "
                  "committed 2026-05-31 results.json baseline remains immutable.",
        "model": runtime_receipt["effective_model"], "runtime_receipt": runtime_receipt,
        "arms": "with_skill (severity+correlation framework) vs baseline (unstructured rank)",
        "run_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "n_runs": n_runs,
        "n_findings": len(fixture["findings"]), "fixture_sha": fixture_sha, "cost_ratio": COST_RATIO,
        "metrics": agg, "verdict": verdict,
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "with_skill": agg["with_skill"], "baseline": agg["baseline"]}, indent=2))
    return results


MAX_TOKENS = 1500  # per-call output budget, applied to BOTH arms; --max-tokens overrides


def main(argv=None):
    global MODEL, RESULTS, RUN_RECEIPT, MAX_TOKENS
    ap = argparse.ArgumentParser(description="triage live efficacy A/B (ranking + correlation)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--historical-reproduction", action="store_true")
    mode.add_argument("--model", help="explicit current-model id")
    ap.add_argument("--approve-covered-model-retention", action="store_true",
                    help="acknowledge mandatory 30-day retention for Fable/Mythos")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--runs", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS,
                    help="per-call output budget for BOTH arms (frozen baseline used 1500)")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--acknowledge-retired-fixture", action="store_true",
                    help=f"run although the fixture status is {FIXTURE_STATUS} (the notice still "
                         "prints); --plan-only never needs it")
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
                   "fixture_status": FIXTURE_STATUS,
                   "fixture_status_since": FIXTURE_STATUS_SINCE,
                   "retired_fixture_acknowledged": args.acknowledge_retired_fixture,
                   "frozen_baseline": {"date": "2026-05-31", "model": HISTORICAL_MODEL,
                                       "sha256": sha256(FROZEN_RESULTS.read_bytes()).hexdigest()}}
    if args.plan_only:
        print(json.dumps(RUN_RECEIPT, indent=2))
        return 0
    print(FIXTURE_STATUS_NOTICE, file=sys.stderr)
    if not args.acknowledge_retired_fixture:
        print(f"error: fixture status is {FIXTURE_STATUS}; pass --acknowledge-retired-fixture to run "
              "anyway (--plan-only needs no acknowledgement; nothing was written)", file=sys.stderr)
        return 2
    MODEL, RESULTS, MAX_TOKENS = model, output, args.max_tokens
    with RUNTIME_LOCK:
        RUNTIME_OBSERVATIONS.clear()
    t0 = time.time()
    try:
        run(args.runs, args.workers)
    except RuntimeQualificationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    print(f"  elapsed {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
