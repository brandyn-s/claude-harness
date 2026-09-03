#!/usr/bin/env python3
"""Live A/B runner for the evaluate-repos efficacy harness (harness/PROBLEM.md).

REQUIRES KEYS — run MANUALLY, never in CI. CI asserts only on committed results.json.

The committed results are a frozen 2026-05-31 Opus 4.8 baseline. Select
`--historical-reproduction` or an explicit `--model`, with a non-frozen
`--output`; there is no implicit current model.

Directly tests the DE-BIAS claim: does the advocate/skeptic harness LOWER false-
dismissal vs a single self-evaluation pass? Both arms decide ADOPT/DEFER/REJECT on the
same neutrally-described patterns, on the explicitly selected model (historical
reproduction uses claude-opus-4-8), NO web_search (pure reasoning
about the pattern vs our architecture). The ONLY difference is single-pass vs
multi-agent:
  * WITH = ADVOCATE (argue FOR) + SKEPTIC (argue AGAINST) -> SYNTHESIS decides (3 calls).
  * BASE = a single self-evaluation pass decides (1 call) — reproduces the dismissal bias.
Scoring is deterministic vs human-curated historical dispositions (grade.py); the
producer never judges itself.

Usage: python3 skills/evaluate-repos/harness/run_live.py --model claude-opus-5 --output /tmp/evaluate-repos.json [--runs 3] [--limit N]
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
VALID_TERMINAL_STOPS = {"end_turn"}
MODEL: str | None = None
RUN_RECEIPT: dict = {}
RUNTIME_OBSERVATIONS: list[dict] = []
RUNTIME_LOCK = Lock()
COST_RATIO = 3.0  # harness = 3 calls vs 1 (advocate + skeptic + synthesis)
MAX_ERROR_RATE = 0.10  # abort threshold: failed-call decisions ("ERROR <type>") / total

ARCH = ("Our Claude Code architecture already has: ~90 skills (gather-*, deep-dive, triage, "
        "investigate, evaluate-repos, ship, etc.), PreToolUse/PostToolUse hooks, a large ambient "
        "rules corpus (git-hygiene, platform-constraints, eval-shipping-discipline, etc.), "
        "subagents via the Agent tool, file-based memory + a knowledge base, and a marketplace "
        "mirror. We value: measured-not-assumed changes, low maintenance overhead, and not "
        "re-adding things we deliberately removed.")

SYSTEM_BASE = ("You are the architecture's own maintainer evaluating whether to ADOPT an external "
               "pattern into it. " + ARCH + " Decide ADOPT, DEFER, or REJECT, with one or two "
               "sentences of reasoning. Output ONLY a fenced ```json block: "
               '{"decision": "<ADOPT|DEFER|REJECT>", "reasoning": "..."}.')

SYS_ADVOCATE = ("You are the ADVOCATE. Make the STRONGEST possible case FOR adopting the given "
                "external pattern into our architecture. " + ARCH + " Find the genuine value even "
                "if it looks familiar or risky. Do NOT give a final ADOPT/DEFER/REJECT verdict — "
                "just argue for adoption in 3-5 sentences.")
SYS_SKEPTIC = ("You are the SKEPTIC. Make the STRONGEST possible case AGAINST adopting the given "
               "external pattern into our architecture. " + ARCH + " Argue it is redundant, risky, "
               "or not worth the cost. Do NOT give a final verdict — just argue against in 3-5 sentences.")
SYS_SYNTH = ("You are the deciding maintainer. Below are an ADVOCATE case (FOR) and a SKEPTIC case "
             "(AGAINST) for adopting an external pattern into our architecture. " + ARCH + " Weigh "
             "both and decide. DECISION DISCIPLINE (over-dismissal guard): a SKEPTIC case always "
             "EXISTS (the skeptic was REQUIRED to argue against), so its mere existence is NOT a "
             "reason to defer or reject. DEFER or REJECT only when the skeptic named a CONCRETE "
             "blocker — a specific redundancy with cited coverage, a specific unacceptable cost, or "
             "a specific conflict. If the advocate's case is sound and the skeptic raised no concrete "
             "disqualifying blocker, ADOPT. Hedging to DEFER merely because both sides have arguments "
             "is the false-dismissal this process exists to prevent. Output ONLY a fenced ```json "
             'block: {"decision": "<ADOPT|DEFER|REJECT>", "reasoning": "..."}.')

_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)
_BARE = re.compile(r"\{[^{}]*\"decision\"[^{}]*\}", re.DOTALL)


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


def _client():
    import anthropic
    return anthropic.Anthropic()


def _say(system: str, user: str, max_tokens: int | None = None) -> str:
    msg = _client().messages.create(model=MODEL, max_tokens=max_tokens or MAX_TOKENS, system=system,
                                    messages=[{"role": "user", "content": user}])
    _record_runtime_response(msg)
    return "".join(getattr(b, "text", "") for b in msg.content if b.type == "text")


def _decision(text: str) -> str:
    cands = [m.group(1) for m in _JSON_BLOCK.finditer(text)][::-1] + \
            [x.group(0) for x in _BARE.finditer(text)][::-1]
    for c in cands:
        try:
            obj = json.loads(c)
            if "decision" in obj:
                return str(obj["decision"])
        except json.JSONDecodeError:
            continue
    return text[-200:]  # fall back to raw tail; normalize_decision will map it


def _one_task(arm: str, p: dict) -> dict:
    desc = f"PATTERN: {p['pattern']}"
    if arm == "baseline":
        dec = _decision(_say(SYSTEM_BASE, desc))
    else:
        adv = _say(SYS_ADVOCATE, desc)
        skep = _say(SYS_SKEPTIC, desc)
        synth = _say(SYS_SYNTH, f"{desc}\n\nADVOCATE (FOR):\n{adv}\n\nSKEPTIC (AGAINST):\n{skep}")
        dec = _decision(synth)
    return {"arm": arm, "id": p["id"], "decision": dec}


def run(n_runs: int, limit, workers: int) -> dict:
    try:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError) as e:
        print(f"error: fixture.json missing or invalid: {e}", file=sys.stderr)
        print(f"hint: expected valid UTF-8 JSON at {FIXTURE}; restore it with "
              "'git checkout -- skills/evaluate-repos/harness/fixture.json'", file=sys.stderr)
        sys.exit(2)
    pats = fixture["patterns"][:limit] if limit else fixture["patterns"]
    fixture_sha = sha256(FIXTURE.read_bytes()).hexdigest()[:12]
    RUNS_DIR.mkdir(exist_ok=True)
    per_arm: dict[str, list[dict]] = {"with_skill": [], "baseline": []}
    transcripts = []
    for ri in range(n_runs):
        tasks = [(a, p) for a in ("with_skill", "baseline") for p in pats]
        recs: list[dict] = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_one_task, a, p): (a, p["id"]) for a, p in tasks}
            for fut in as_completed(futs):
                a, pid = futs[fut]
                try:
                    recs.append(fut.result())
                except Exception as e:
                    recs.append({"arm": a, "id": pid, "decision": f"ERROR {type(e).__name__}"})
        for a in per_arm:
            per_arm[a].append(grade.score_run(fixture, [r for r in recs if r["arm"] == a]))
        transcripts.append({"run_idx": ri, "records": recs})
        print(f"  run {ri+1}/{n_runs} done ({len(recs)} decisions)")
    (RUNS_DIR / f"transcripts-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json").write_text(
        json.dumps(transcripts, indent=2), encoding="utf-8")
    n_total = sum(len(t["records"]) for t in transcripts)
    n_err = sum(1 for t in transcripts for r in t["records"]
                if str(r["decision"]).startswith("ERROR "))
    if n_total and (n_err / n_total) > MAX_ERROR_RATE:
        print(f"error: {n_err}/{n_total} API calls failed (recorded as 'ERROR <type>' decisions); "
              "refusing to compute a verdict or write results.json from a failed measurement",
              file=sys.stderr)
        print("hint: check ANTHROPIC_API_KEY / network, inspect the failure types in the "
              "transcripts-*.json just written under harness/runs/, then re-run", file=sys.stderr)
        sys.exit(1)
    agg = {a: grade.aggregate_runs(per_arm[a]) for a in per_arm}
    # Phase B: attach paired-bootstrap CI vs baseline for the CI-aware verdict.
    if grade.stats is not None:
        grade.stats.attach_ci(agg["with_skill"], agg["baseline"], grade._METRIC_KEYS)
    verdict = grade.decide_verdict(agg["with_skill"], agg["baseline"], min_delta=0.05)
    runtime_receipt = _qualified_runtime_receipt()
    results = {
        "_about": "MEASURED evaluate-repos A/B output from an explicit harness mode; "
                  "the committed 2026-05-31 results.json baseline remains immutable.",
        "model": runtime_receipt["effective_model"], "runtime_receipt": runtime_receipt,
        "arms": "with_skill (advocate+skeptic+synthesis) vs baseline (single self-eval)",
        "run_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "n_runs": n_runs,
        "n_patterns": len(pats), "fixture_sha": fixture_sha, "cost_ratio": COST_RATIO,
        "metrics": agg, "verdict": verdict,
    }
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "with_skill": agg["with_skill"], "baseline": agg["baseline"]}, indent=2))
    return results


MAX_TOKENS = 700  # per-call output budget, applied to BOTH arms; --max-tokens overrides


def main(argv=None):
    global MODEL, RESULTS, RUN_RECEIPT, MAX_TOKENS
    ap = argparse.ArgumentParser(description="evaluate-repos live efficacy A/B (de-bias)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--historical-reproduction", action="store_true")
    mode.add_argument("--model", help="explicit current-model id")
    ap.add_argument("--approve-covered-model-retention", action="store_true",
                    help="acknowledge mandatory 30-day retention for Fable/Mythos")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--runs", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=MAX_TOKENS,
                    help="per-call output budget for BOTH arms (frozen baseline used 700)")
    ap.add_argument("--limit", type=int, default=None)
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
    RUN_RECEIPT = {
        "mode": "historical_reproduction" if args.historical_reproduction else "current_model",
        "requested_model": model, "max_tokens": args.max_tokens, "qualification_status": "UNVERIFIED",
        "effective_model": "<unavailable>", "provider": "<unavailable>",
        "refusal_detected": "<unavailable>", "truncation_detected": "<unavailable>",
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
