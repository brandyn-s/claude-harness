#!/usr/bin/env python3
"""Live A/B runner for the deep-dive efficacy harness (harness/PROBLEM.md).

REQUIRES KEYS — run MANUALLY, never in CI. CI asserts only on committed results.json.

The committed results are a frozen 2026-05-31 Opus 4.8 baseline. This runner
has no default model: select `--historical-reproduction` or an explicit
`--model`, and write to an explicit non-frozen `--output` path.

Measures deep-dive's value-prop: CONFIDENCE CALIBRATION + counterfactual substance
(not grounding). Both arms answer the SAME factual questions on the SAME best model
explicitly selected model with the SAME hosted web_search (historical reproduction
uses claude-opus-4-8); the ONLY difference is the system
prompt:
  * WITH = deep-dive's three-layer framework (evidence-graded HIGH/MEDIUM/LOW
           confidence + a per-finding counterfactual with SURVIVES/COLLAPSES/
           AMBIGUOUS; reject false premises rather than confirm).
  * BASE = a strong plain pass that still emits a confidence label (so calibration
           is comparable), no framework, no counterfactual.
Scoring is deterministic correctness vs human answer keys + calibration analysis
(grade.py). Producer never judges itself.

Usage:
    python3 skills/deep-dive/harness/run_live.py --historical-reproduction --output /tmp/deep-dive-history.json
    python3 skills/deep-dive/harness/run_live.py --model claude-opus-5 --output /tmp/deep-dive-current.json --runs 1 --limit 3
Env: ANTHROPIC_API_KEY only.
"""
from __future__ import annotations

import argparse
import json
import os
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
sys.path.insert(0, str(HARNESS.parents[2] / "scripts"))
sys.path.insert(0, str(Path.cwd() / "scripts"))
import grade  # type: ignore  # noqa: E402
from qualification_provenance import (  # noqa: E402
    add_qualification_arguments,
    failed_trial_provenance,
    qualification_metadata,
    response_trial_provenance,
)

FIXTURE = HARNESS / "fixture.json"
FROZEN_RESULTS = HARNESS / "results.json"
RESULTS = FROZEN_RESULTS
RUNS_DIR = HARNESS / "runs"

HISTORICAL_MODEL = "claude-opus-4-8"
COVERED_MODELS = {"claude-fable-5", "claude-mythos-5"}
VALID_TERMINAL_STOPS = {"end_turn"}
MODEL: str | None = None
EFFORT_CONFIG = {"effort": "high"}
PROVIDER = "anthropic-api"
RUN_RECEIPT: dict = {}
RUNTIME_OBSERVATIONS: list[dict] = []
RUNTIME_LOCK = Lock()
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 4}
COST_RATIO = 4.0  # deep-dive ~ multi-provider waves + synthesis
GRADER_CONFIG = {
    "grader": "grade.py",
    "metric_keys": list(grade._METRIC_KEYS),
    "minimum_delta": 0.05,
    "cost_ratio": COST_RATIO,
}

SYSTEM_WITH = """You are a research analyst applying a strict three-layer evidence \
framework. For the given question:
1. Use web_search to find current evidence. If the question rests on a FALSE or \
unverifiable premise (a paper/benchmark/figure that does not exist), do NOT confirm \
it — say plainly that you can find no such thing.
2. Give your best ANSWER.
3. Assign a CONFIDENCE of HIGH / MEDIUM / LOW that honestly reflects evidence quality \
and corroboration: HIGH only when multiple credible current sources agree; LOW when \
sources are thin, conflicting, the premise is dubious, or the answer may be outdated.
4. Provide a COUNTERFACTUAL: state the inverted hypothesis and a verdict of \
SURVIVES / COLLAPSES / AMBIGUOUS — specific enough that someone could disprove your \
answer by checking it.

Output ONLY a final fenced ```json block: {"answer": "...", \
"confidence": "<HIGH|MEDIUM|LOW>", "counterfactual": "<inverted hypothesis + SURVIVES|COLLAPSES|AMBIGUOUS>"}."""

SYSTEM_BASE = """You are a knowledgeable research assistant. Answer the given question \
using web_search. Then state your confidence as exactly one of HIGH / MEDIUM / LOW.

Output ONLY a final fenced ```json block: {"answer": "...", "confidence": "<HIGH|MEDIUM|LOW>"}."""

ARMS = {"with_skill": SYSTEM_WITH, "baseline": SYSTEM_BASE}
USER_TMPL = "Question:\n\n{q}\n\nResearch it and return your JSON."

_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
_BARE_OBJ = re.compile(r"\{[^{}]*\"answer\"[^{}]*\}", re.DOTALL)


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
    observation = {
        "effective_model": effective_model,
        "stop_reason": stop_reason,
        "terminal": terminal,
        "refusal_detected": refusal,
        "truncation_detected": truncation,
        "failures": failures,
    }
    with RUNTIME_LOCK:
        RUNTIME_OBSERVATIONS.append(observation)


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
    return {
        **RUN_RECEIPT,
        "qualification_status": "QUALIFIED",
        "effective_model": MODEL,
        "provider": PROVIDER,
        "effort": EFFORT_CONFIG["effort"],
        "refusal_detected": False,
        "truncation_detected": False,
        "stop_outcomes": stop_outcomes,
        "response_count": len(observations),
        "terminal_response_count": terminal_count,
    }


def _extract_json(text: str) -> dict:
    cands = [m.group(1) for m in _JSON_BLOCK.finditer(text)][::-1]
    cands += [x.group(0) for x in _BARE_OBJ.finditer(text)][::-1]
    for c in cands:
        try:
            obj = json.loads(c)
            if "answer" in obj:
                obj.setdefault("confidence", "")
                obj.setdefault("counterfactual", "")
                return obj
        except json.JSONDecodeError:
            continue
    return {"answer": text[-600:], "confidence": "", "counterfactual": "", "_parse": "fallback"}


def _call_arm(system: str, q: str) -> tuple[dict, list[dict]]:
    import anthropic
    client = anthropic.Anthropic()
    messages: list[dict] = [{"role": "user", "content": USER_TMPL.format(q=q)}]
    full, guard = "", 0
    response_provenance = []
    while True:
        guard += 1
        msg = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS, system=system,
                                     output_config=EFFORT_CONFIG,
                                     tools=[WEB_SEARCH_TOOL], messages=messages)  # type: ignore[arg-type]
        stop_reason = getattr(msg, "stop_reason", None)
        _record_runtime_response(
            msg, terminal=stop_reason != "pause_turn" or guard >= 4
        )
        response_provenance.append(response_trial_provenance(
            response=msg, requested_model=MODEL, provider=PROVIDER,
            grader_config=GRADER_CONFIG))  # type: ignore[arg-type]
        full += "".join(getattr(b, "text", "") for b in msg.content if b.type == "text")
        if stop_reason == "pause_turn" and guard < 4:
            messages.append({"role": "assistant", "content": msg.content})
            continue
        break
    return _extract_json(full), response_provenance


def _one_task(arm: str, system: str, q: dict) -> dict:
    obj, response_provenance = _call_arm(system, q["q"])
    return {"arm": arm, "id": q["id"], "answer_text": obj.get("answer", ""),
            "confidence": obj.get("confidence", ""), "counterfactual": obj.get("counterfactual", ""),
            "_response_provenance": response_provenance}


def run(n_runs: int, limit, workers: int) -> dict:
    assert MODEL is not None, "select a qualification model before running"
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    qs = fixture["questions"][:limit] if limit else fixture["questions"]
    fixture_sha = sha256(FIXTURE.read_bytes()).hexdigest()[:12]
    RUNS_DIR.mkdir(exist_ok=True)
    per_arm: dict[str, list[dict]] = {a: [] for a in ARMS}
    transcripts = []
    run_date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for ri in range(n_runs):
        tasks = [(a, s, q) for a, s in ARMS.items() for q in qs]
        recs: list[dict] = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_one_task, a, s, q): (a, q["id"]) for a, s, q in tasks}
            for fut in as_completed(futs):
                a, qid = futs[fut]
                try:
                    recs.append(fut.result())
                except Exception as e:
                    recs.append({"arm": a, "id": qid, "answer_text": f"ERROR {type(e).__name__}: {e}",
                                 "confidence": "", "counterfactual": "",
                                 "_response_provenance": [failed_trial_provenance(
                                     requested_model=MODEL, provider=PROVIDER,
                                     grader_config=GRADER_CONFIG, failure=type(e).__name__)]})
        errors = [r for r in recs if r["answer_text"].startswith("ERROR ")]
        if recs and len(errors) == len(recs):
            print(f"error: run {ri+1}/{n_runs} failed systemically — all {len(recs)} tasks errored "
                  f"(first: {errors[0]['answer_text'][:160]})", file=sys.stderr)
            print("hint: check API key validity / network and re-run; the committed results.json "
                  "was left untouched", file=sys.stderr)
            sys.exit(2)
        for a in ARMS:
            # run_date selects the dated answer key for currency questions (grade.key_for)
            per_arm[a].append(grade.score_run(fixture, [r for r in recs if r["arm"] == a],
                                              run_date=run_date_str))
        transcripts.append({"run_idx": ri, "records": recs})
        print(f"  run {ri+1}/{n_runs} done ({len(recs)} tasks)")
    (RUNS_DIR / f"transcripts-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json").write_text(
        json.dumps(transcripts, indent=2), encoding="utf-8")
    (RUNS_DIR / f"sample-records-{run_date_str}.json").write_text(
        json.dumps({"_about": "Per-run records sample for "
                    "test_results_reproducible_from_committed_sample.", "runs": transcripts},
                   indent=2), encoding="utf-8")
    agg = {a: grade.aggregate_runs(per_arm[a]) for a in ARMS}
    # Phase B: attach paired-bootstrap CI vs baseline for the CI-aware verdict.
    if grade.stats is not None:
        grade.stats.attach_ci(agg["with_skill"], agg["baseline"], grade._METRIC_KEYS)
    verdict = grade.decide_verdict(agg["with_skill"], agg["baseline"], min_delta=0.05)
    trial_provenance = [
        item
        for transcript in transcripts
        for record in transcript["records"]
        for item in record["_response_provenance"]
    ]
    qualification = qualification_metadata(
        requested_model=MODEL, effort=EFFORT_CONFIG["effort"], provider=PROVIDER,
        trial_provenance=trial_provenance, grader_config=GRADER_CONFIG,
        config_paths=[Path(__file__), FIXTURE, HARNESS / "grade.py"])
    if qualification["qualification_status"] != "valid":
        raise RuntimeQualificationError(
            "trial provenance qualification failed: "
            f"{qualification['qualification_status']} ({qualification['response_state']})"
        )
    runtime_receipt = _qualified_runtime_receipt()
    results = {
        "_about": "MEASURED deep-dive A/B output from an explicit harness mode; the "
                  "committed 2026-05-31 results.json baseline remains immutable.",
        "model": runtime_receipt["effective_model"], "requested_model": MODEL,
        "qualification": qualification, "runtime_receipt": runtime_receipt,
        "arms": "with_skill (3-layer framework) vs baseline (plain + confidence)",
        "run_date": run_date_str, "n_runs": n_runs,
        "n_questions": len(qs), "fixture_sha": fixture_sha, "cost_ratio": COST_RATIO,
        "metrics": agg, "verdict": verdict,
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "with_skill": agg["with_skill"], "baseline": agg["baseline"]}, indent=2))
    return results


MAX_TOKENS = 1500  # per-call output budget, applied to BOTH arms; --max-tokens overrides


def main(argv=None):
    global MODEL, RESULTS, RUN_RECEIPT, EFFORT_CONFIG, PROVIDER, MAX_TOKENS
    ap = argparse.ArgumentParser(description="deep-dive live efficacy A/B (calibration)")
    ap.add_argument("--historical-reproduction", action="store_true")
    ap.add_argument("--approve-covered-model-retention", action="store_true",
                    help="acknowledge mandatory 30-day retention for Fable/Mythos")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--runs", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS,
                    help="per-call output budget for BOTH arms (frozen baseline used 1500)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=5)
    add_qualification_arguments(ap, require_model=False)
    args = ap.parse_args(argv)
    if bool(args.historical_reproduction) == bool(args.model):
        ap.error("select exactly one of --historical-reproduction or --model")
    model = HISTORICAL_MODEL if args.historical_reproduction else args.model
    if not args.historical_reproduction and model == HISTORICAL_MODEL:
        ap.error("Opus 4.8 is historical; use --historical-reproduction")
    if not isinstance(model, str) or not re.fullmatch(r"claude-[a-z0-9-]+", model):
        ap.error("--model must be an explicit Claude model id")
    if args.provider != "anthropic-api":
        ap.error("this harness calls the Anthropic API directly; --provider must be anthropic-api")
    if model in COVERED_MODELS and not args.approve_covered_model_retention:
        ap.error("Fable 5 and Mythos 5 require explicit approval of mandatory 30-day retention")
    output = args.output.expanduser().resolve()
    if output == FROZEN_RESULTS.resolve():
        ap.error("the frozen 2026-05-31 results.json is immutable")
    RUN_RECEIPT = {
        "mode": "historical_reproduction" if args.historical_reproduction else "current_model",
        "requested_model": model,
        "max_tokens": args.max_tokens,
        "effort": args.effort,
        "provider": "<unavailable>",
        "qualification_status": "UNVERIFIED",
        "effective_model": "<unavailable>",
        "refusal_detected": "<unavailable>",
        "truncation_detected": "<unavailable>",
        "stop_outcomes": "<unavailable>",
        "covered_model_retention_required": model in COVERED_MODELS,
        "covered_model_retention_approved": model in COVERED_MODELS and args.approve_covered_model_retention,
        "output_path": str(output),
        "frozen_baseline": {"date": "2026-05-31", "model": HISTORICAL_MODEL,
                            "sha256": sha256(FROZEN_RESULTS.read_bytes()).hexdigest()},
    }
    if args.plan_only:
        print(json.dumps(RUN_RECEIPT, indent=2))
        return 0
    MODEL, RESULTS, MAX_TOKENS = model, output, args.max_tokens
    EFFORT_CONFIG, PROVIDER = {"effort": args.effort}, args.provider
    with RUNTIME_LOCK:
        RUNTIME_OBSERVATIONS.clear()
    try:
        import anthropic  # noqa: F401
    except ImportError as e:
        print(f"error: anthropic SDK not importable ({e})", file=sys.stderr)
        print("hint: pip install anthropic, then re-run", file=sys.stderr)
        return 2
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("error: no Anthropic credentials — ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) is not set",
              file=sys.stderr)
        print("hint: export ANTHROPIC_API_KEY=... and re-run; results.json was NOT touched", file=sys.stderr)
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
