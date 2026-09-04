#!/usr/bin/env python3
"""Live A/B: does the precompact-priorities checklist improve recall after compaction?

REQUIRES KEYS -- run MANUALLY, never in CI. CI asserts on the committed
results.json only (test_compaction_eval.py). Deps beyond the stdlib: anthropic.

What is measured
----------------
hooks/precompact-priorities.py prints a checklist that Claude Code appends to the
compaction summarizer's prompt as `Additional Instructions` (channel evidence in
the hook docstring). This runner reproduces that assembly byte-for-byte
(compact_prompt.py) and asks: does the appended text make the SUMMARY carry the
facts a resumed session needs?

Arms -- the ONLY difference is the final user message the summarizer receives:
  baseline         Claude Code's default compaction prompt, nothing appended
  with_priorities  the same prompt + "\\nAdditional Instructions:\\n" + the exact
                   PRIORITIES text the hook prints

Per run and arm: (1) the summarizer sees fixture.py's ~60-turn transcript as real
alternating messages plus the arm's prompt; (2) a reader model sees ONLY the
extracted <summary> (what survives compaction, compact_prompt.extract_summary)
and answers the fixed 22-question recovery questionnaire, saying UNKNOWN when
the summary lacks the fact; (3) grade.py checks every answer against the planted
key by string/number match. The primary metric is overall recall; the verdict is
the paired-bootstrap CI rule from skills/_shared/stats.py (keep / trim / blocked
on measurement), with per-category recall reported for both arms.

Cost discipline: the run is priced before any request (--plan-only prints the
same receipt with no network) and aborts when the estimate exceeds --max-cost-usd
(default 15). The API key is read from the environment only; the receipt records
its byte length, never its value.

Model notes: --model must be an exact Claude id (aliases rejected). Thinking is
left at the model's default (Fable 5.x: always on, shares --max-tokens with the
text), which is why --effort defaults to medium for the summarizer; the reader
runs at low effort in both arms. No server-side fallbacks: a fallback would swap
the model under test, so a refusal or a model mismatch fails the trial instead.

Budget: a summary that stops on max_tokens is an INVALID trial, not a low score.
Production compaction runs with a 64k output ceiling and never ships a cut
summary, so grading one measures where the cut fell, not the instruction. The
2026-09-03 smoke at --max-tokens 4000 on claude-fable-5-1 (effort medium) cut
BOTH arms: baseline inside section 2, with_priorities before its <summary> even
opened (its analysis block then scored 0.64 against baseline's 0.23, which is
exactly the artifact this rule exists to exclude). The default is therefore
16000; the receipt records whatever ran.

Usage:
  uv run --with anthropic python3 skills/_shared/compaction-eval/run_live.py \\
      --plan-only --model claude-fable-5-1 --output /tmp/compaction-eval.json
  uv run --with anthropic python3 skills/_shared/compaction-eval/run_live.py \\
      --runs 3 --model claude-fable-5-1 --max-tokens 4000 \\
      --output skills/_shared/compaction-eval/results.json
  uv run --with anthropic python3 skills/_shared/compaction-eval/run_live.py \\
      --fixture incident --runs 3 --model claude-fable-5-1 \\
      --output skills/_shared/compaction-eval/results-incident.json
Env: ANTHROPIC_API_KEY only. --fixture selects the planted-fact transcript (coding,
the default, or incident); combine_results.py pools the paired deltas of several
results files into one CI.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
HOOK_PATH = REPO / "hooks" / "precompact-priorities.py"
sys.path.insert(0, str(REPO / "scripts"))
from qualification_provenance import (  # noqa: E402
    add_qualification_arguments,
    failed_trial_provenance,
    qualification_metadata,
    response_trial_provenance,
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, path
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Two planted-fact fixtures with the same question shape (22 questions, 7 categories):
# `coding` is fixture.py (a flaky-test debugging session), `incident` is
# fixture_incident.py (a production 5xx incident on Kubernetes). --fixture picks one;
# the results file records which, and RESULTS.md reports both plus the pooled CI.
FIXTURES = {"coding": "fixture.py", "incident": "fixture_incident.py"}
DEFAULT_FIXTURE = "coding"
FIXTURE_NAME = DEFAULT_FIXTURE


def load_fixture_module(name: str):
    return _load(f"compaction_eval_fixture_{name}", HERE / FIXTURES[name])


fixture_mod = load_fixture_module(DEFAULT_FIXTURE)
grade = _load("compaction_eval_grade", HERE / "grade.py")
compact_prompt = _load("compaction_eval_prompt", HERE / "compact_prompt.py")
PRIORITIES: str = _load("precompact_priorities_hook", HOOK_PATH).PRIORITIES

ARMS = {
    "baseline": compact_prompt.build_compact_prompt(None),
    "with_priorities": compact_prompt.build_compact_prompt(PRIORITIES),
}
PROVIDER = "anthropic-api"
VALID_TERMINAL_STOPS = {"end_turn"}
DEFAULT_MAX_TOKENS = 16000
DEFAULT_RUNS = 3
DEFAULT_COST_CAP_USD = 15.0
READER_EFFORT = "low"
# USD per 1M tokens (input, output). Anthropic first-party rates, claude-api skill
# table cached 2026-06-24. Unknown ids are priced at the top tier so an estimate
# can only err high.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0), "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5-1": (10.0, 50.0), "claude-mythos-5": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0), "claude-opus-4-8": (5.0, 25.0), "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0), "claude-sonnet-5": (2.0, 10.0), "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
TOP_TIER = (10.0, 50.0)

READER_SYSTEM = (
    "You are resuming an engineering session after context compaction. The ONLY record you "
    "have of the earlier work is the summary in the user message. Answer each question strictly "
    "from that summary. If the summary does not contain the information, answer exactly UNKNOWN. "
    "Do not guess, do not infer from general knowledge, do not use tools. Keep each answer short: "
    "the id, sha, number, quoted line, label, file:line, or a one-sentence decision-plus-reason "
    "as the question asks. Respond with a single JSON object mapping each question id to its "
    "answer string and nothing else."
)

MODEL: str | None = None
EFFORT = "medium"
MAX_TOKENS = DEFAULT_MAX_TOKENS
USAGE_LOCK = Lock()
USAGE = {"input_tokens": 0, "output_tokens": 0, "calls": 0}
GRADER_CONFIG = {"grader": "grade.py", "metric_keys": list(grade.METRIC_KEYS), "primary": grade.PRIMARY_METRIC}


class TrialError(RuntimeError):
    """One arm of one run could not produce a gradable summary."""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _approx_tokens(text: str) -> int:
    # Conservative heuristic for planning: code/log-heavy text runs ~3.2 chars per token.
    return int(len(text) / 3.2) + 1


def reader_user_message(summary: str, questions: list[dict]) -> str:
    qs = "\n".join(f"{q['id']}: {q['q']}" for q in questions)
    return (f"<summary>\n{summary}\n</summary>\n\nQuestions (answer each from the summary only; "
            f"UNKNOWN when it is not there):\n{qs}\n\nReturn one JSON object: "
            f'{{"{questions[0]["id"]}": "...", ...}}')


def estimate_cost(model: str, transcript_tokens: int, prompt_tokens: dict[str, int],
                  reader_prompt_tokens: int, max_tokens: int, runs: int) -> dict:
    """Worst-case spend: every call emits max_tokens, the reader sees a max-size summary."""
    price_in, price_out = PRICES.get(model, TOP_TIER)
    per_run_in = sum(transcript_tokens + p for p in prompt_tokens.values())      # summaries
    per_run_in += len(prompt_tokens) * (reader_prompt_tokens + max_tokens)       # readers
    per_run_out = len(prompt_tokens) * 2 * max_tokens
    total_in, total_out = per_run_in * runs, per_run_out * runs
    usd = total_in / 1e6 * price_in + total_out / 1e6 * price_out
    return {"model_priced_as": model if model in PRICES else f"{model} (unknown id, top tier assumed)",
            "price_per_mtok": {"input": price_in, "output": price_out},
            "transcript_tokens": transcript_tokens, "prompt_tokens": prompt_tokens,
            "reader_prompt_tokens": reader_prompt_tokens, "worst_case_input_tokens": total_in,
            "worst_case_output_tokens": total_out, "estimated_cost_usd": round(usd, 2)}


def actual_cost_usd(model: str, usage: dict) -> float:
    price_in, price_out = PRICES.get(model, TOP_TIER)
    return round(usage["input_tokens"] / 1e6 * price_in + usage["output_tokens"] / 1e6 * price_out, 4)


def _record_usage(msg) -> None:
    u = getattr(msg, "usage", None)
    with USAGE_LOCK:
        USAGE["calls"] += 1
        USAGE["input_tokens"] += int(getattr(u, "input_tokens", 0) or 0)
        USAGE["output_tokens"] += int(getattr(u, "output_tokens", 0) or 0)


def _text_of(msg) -> str:
    return "".join(getattr(b, "text", "") for b in getattr(msg, "content", []) if getattr(b, "type", "") == "text")


def _check(msg, what: str) -> None:
    if getattr(msg, "model", None) != MODEL:
        raise TrialError(f"{what}: model mismatch, requested {MODEL} got {getattr(msg, 'model', None)!r}")
    stop = getattr(msg, "stop_reason", None)
    if stop == "refusal":
        raise TrialError(f"{what}: provider refusal ({getattr(getattr(msg, 'stop_details', None), 'category', None)})")
    if stop == "max_tokens":
        raise TrialError(f"{what}: truncated at max_tokens={MAX_TOKENS}; raise --max-tokens (a cut summary "
                         "is a harness artifact, production compaction runs with a 64k output ceiling)")
    if stop not in VALID_TERMINAL_STOPS:
        raise TrialError(f"{what}: unexpected stop_reason {stop!r}")


def _call(client, messages: list[dict], effort: str, system: str | None = None):
    kwargs = dict(model=MODEL, max_tokens=MAX_TOKENS, messages=messages, output_config={"effort": effort})
    if system:
        kwargs["system"] = system
    msg = client.messages.create(**kwargs)
    _record_usage(msg)
    return msg


def run_trial(client, arm: str, fixture: dict, run_idx: int) -> dict:
    """Summarize with the arm's prompt, then read the questionnaire from the summary."""
    messages = [dict(t) for t in fixture["transcript"]] + [{"role": "user", "content": ARMS[arm]}]
    summary_msg = _call(client, messages, EFFORT)
    _check(summary_msg, f"summary[{arm} run {run_idx}]")
    raw_summary = _text_of(summary_msg)
    summary = compact_prompt.extract_summary(raw_summary)
    if not summary.strip():
        raise TrialError(f"summary[{arm} run {run_idx}]: empty text (stop_reason={summary_msg.stop_reason})")
    summary_tag_found = "<summary>" in raw_summary and "</summary>" in raw_summary
    reader_msg = _call(client, [{"role": "user", "content": reader_user_message(summary, fixture["questions"])}],
                       READER_EFFORT, system=READER_SYSTEM)
    _check(reader_msg, f"reader[{arm} run {run_idx}]")
    ids = [q["id"] for q in fixture["questions"]]
    answers = grade.parse_answers(_text_of(reader_msg), ids)
    scored = grade.score_run(fixture, answers)
    provenance = [response_trial_provenance(response=m, requested_model=MODEL, provider=PROVIDER,
                                            grader_config=GRADER_CONFIG) for m in (summary_msg, reader_msg)]
    return {
        "arm": arm, "run_idx": run_idx,
        "summary_stop_reason": summary_msg.stop_reason, "summary_tag_found": summary_tag_found,
        "reader_stop_reason": reader_msg.stop_reason,
        "summary_chars": len(summary), "summary": summary, "answers": answers,
        "scores": {k: scored[k] for k in grade.METRIC_KEYS}, "rows": scored["rows"],
        "usage": {"summary": _usage_dict(summary_msg), "reader": _usage_dict(reader_msg)},
        "_response_provenance": provenance,
    }


def _usage_dict(msg) -> dict:
    u = getattr(msg, "usage", None)
    return {"input_tokens": int(getattr(u, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(u, "output_tokens", 0) or 0)}


def run(n_runs: int, workers: int, output: Path, receipt: dict, cost_cap: float) -> int:
    import anthropic
    client = anthropic.Anthropic()
    fixture = fixture_mod.build_fixture()
    # Exact input count before spending anything (count_tokens is free).
    counted = client.messages.count_tokens(model=MODEL, messages=fixture["transcript"]).input_tokens
    reader_tokens = _approx_tokens(reader_user_message("", fixture["questions"]) + READER_SYSTEM)
    estimate = estimate_cost(MODEL, counted, {a: _approx_tokens(p) for a, p in ARMS.items()},
                             reader_tokens, MAX_TOKENS, n_runs)
    receipt["estimate_exact_input"] = estimate
    if estimate["estimated_cost_usd"] > cost_cap:
        print(f"error: worst-case estimate ${estimate['estimated_cost_usd']:.2f} exceeds the "
              f"${cost_cap:.2f} cap after exact token counting; nothing was spent", file=sys.stderr)
        return 2
    print(f"  transcript {counted} tokens (exact); worst case ${estimate['estimated_cost_usd']:.2f} "
          f"<= cap ${cost_cap:.2f}; running {n_runs} runs x {len(ARMS)} arms")

    records: list[dict] = []
    errors: list[dict] = []
    tasks = [(arm, ri) for ri in range(n_runs) for arm in ARMS]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(run_trial, client, arm, fixture, ri): (arm, ri) for arm, ri in tasks}
        for fut in as_completed(futs):
            arm, ri = futs[fut]
            try:
                rec = fut.result()
                records.append(rec)
                print(f"  {arm:<16} run {ri + 1}/{n_runs}: recall {rec['scores']['recall']:.3f}"
                      f"{'' if rec['summary_tag_found'] else ' (no <summary> tag; text kept as-is, like v5o)'}")
            except Exception as exc:  # noqa: BLE001 - one failed trial must not hide the others
                errors.append({"arm": arm, "run_idx": ri, "error": f"{type(exc).__name__}: {exc}"[:400],
                               "_response_provenance": [failed_trial_provenance(
                                   requested_model=MODEL, provider=PROVIDER, grader_config=GRADER_CONFIG,
                                   failure=type(exc).__name__)]})
                print(f"  {arm:<16} run {ri + 1}/{n_runs}: ERROR {type(exc).__name__}: {str(exc)[:160]}",
                      file=sys.stderr)
    if errors and len(errors) == len(tasks):
        print("error: every trial failed; check the key, network and model id. Nothing written.",
              file=sys.stderr)
        return 2

    # Pair runs index-for-index; a run with a failed arm is dropped from the CI (both arms).
    complete_runs = sorted({r["run_idx"] for r in records
                            if all(any(x["arm"] == a and x["run_idx"] == r["run_idx"] for x in records)
                                   for a in ARMS)})
    per_arm = {a: [next(x for x in records if x["arm"] == a and x["run_idx"] == ri)["scores"]
                   for ri in complete_runs] for a in ARMS}
    agg = {a: grade.aggregate_runs(per_arm[a]) for a in ARMS}
    verdict = grade.decide_verdict(agg["with_priorities"], agg["baseline"])
    per_category = {cat: {a: (agg[a].get(f"recall_{cat}") or {}).get("mean") for a in ARMS}
                    for cat in grade.CATEGORIES}
    per_question = {}
    for q in fixture["questions"]:
        per_question[q["id"]] = {a: sum(1 for r in records if r["arm"] == a
                                        for row in r["rows"] if row["id"] == q["id"] and row["correct"])
                                 for a in ARMS}
    trial_provenance = [p for r in records + errors for p in r["_response_provenance"]]
    qualification = qualification_metadata(
        requested_model=MODEL, effort=EFFORT, provider=PROVIDER, trial_provenance=trial_provenance,
        grader_config=GRADER_CONFIG,
        config_paths=[Path(__file__), HERE / FIXTURES[FIXTURE_NAME], HERE / "grade.py", HERE / "compact_prompt.py",
                      HOOK_PATH])
    results = {
        "_about": "MEASURED compaction A/B: baseline (Claude Code default compaction prompt) vs "
                  "with_priorities (same + hooks/precompact-priorities.py text). Reader answers from the "
                  f"summary only; grade.py scores deterministically. Fixture `{FIXTURE_NAME}` "
                  f"({FIXTURES[FIXTURE_NAME]}). Produced by run_live.py.",
        "run_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "requested_model": MODEL, "effective_model": qualification["effective_model"],
        "effort": {"summarizer": EFFORT, "reader": READER_EFFORT}, "max_tokens": MAX_TOKENS,
        "n_runs_requested": n_runs, "n_runs_paired": len(complete_runs),
        "fixture": FIXTURE_NAME, "fixture_file": FIXTURES[FIXTURE_NAME],
        "fixture_sha": fixture_mod.fixture_sha(fixture), "hook_text_sha": _sha(PRIORITIES),
        "hook_text_bytes": len(PRIORITIES.encode("utf-8")),
        "arms": {a: {"prompt_sha": _sha(p), "prompt_chars": len(p)} for a, p in ARMS.items()},
        "receipt": receipt, "qualification": qualification,
        "cost": {**estimate, "actual_usd": actual_cost_usd(MODEL, USAGE), "actual_usage": dict(USAGE)},
        "metrics": agg, "per_category_recall_mean": per_category,
        "per_question_correct_count": per_question, "verdict": verdict,
        "errors": errors, "records": sorted(records, key=lambda r: (r["run_idx"], r["arm"])),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": verdict, "recall": {a: agg[a].get("recall") for a in ARMS},
                      "per_category_recall_mean": per_category,
                      "cost_usd": results["cost"]["actual_usd"], "errors": len(errors)}, indent=2))
    return 0


def main(argv=None) -> int:
    global MODEL, EFFORT, MAX_TOKENS, FIXTURE_NAME, fixture_mod
    ap = argparse.ArgumentParser(description="compaction-priorities live A/B (recall after compaction)")
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--fixture", choices=sorted(FIXTURES), default=DEFAULT_FIXTURE,
                    help="planted-fact transcript to summarize: coding (fixture.py) or incident (fixture_incident.py)")
    ap.add_argument("--plan-only", action="store_true", help="print the receipt and cost estimate; no network")
    ap.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    ap.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
                    help="per-call output budget for BOTH arms and both roles")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-cost-usd", type=float, default=DEFAULT_COST_CAP_USD,
                    help="abort before any request when the worst-case estimate exceeds this")
    add_qualification_arguments(ap, require_model=True)
    ap.set_defaults(effort="medium")
    args = ap.parse_args(argv)
    if args.provider != PROVIDER:
        ap.error("this harness calls the Anthropic API directly; --provider must be anthropic-api")
    if args.runs < 1:
        ap.error("--runs must be >= 1")
    output = args.output.expanduser().resolve()
    MODEL, EFFORT, MAX_TOKENS = args.model, args.effort, args.max_tokens
    FIXTURE_NAME = args.fixture
    fixture_mod = load_fixture_module(FIXTURE_NAME)

    fixture = fixture_mod.build_fixture()
    transcript_tokens = _approx_tokens(fixture_mod.transcript_text(fixture))
    reader_tokens = _approx_tokens(reader_user_message("", fixture["questions"]) + READER_SYSTEM)
    estimate = estimate_cost(MODEL, transcript_tokens, {a: _approx_tokens(p) for a, p in ARMS.items()},
                             reader_tokens, MAX_TOKENS, args.runs)
    key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN") or ""
    receipt = {
        "mode": "current_model", "requested_model": MODEL, "effort": {"summarizer": EFFORT, "reader": READER_EFFORT},
        "max_tokens": MAX_TOKENS, "runs": args.runs, "arms": list(ARMS), "provider": PROVIDER,
        "fixture": FIXTURE_NAME, "fixture_file": FIXTURES[FIXTURE_NAME],
        "fixture_sha": fixture_mod.fixture_sha(fixture), "fixture_turns": len(fixture["transcript"]),
        "fixture_questions": len(fixture["questions"]), "hook_text_sha": _sha(PRIORITIES),
        "hook_text_bytes": len(PRIORITIES.encode("utf-8")), "cost_cap_usd": args.max_cost_usd,
        "estimate_heuristic": estimate, "within_budget": estimate["estimated_cost_usd"] <= args.max_cost_usd,
        "credential_bytes": len(key), "output_path": str(output),
    }
    if args.plan_only:
        print(json.dumps(receipt, indent=2))
        return 0
    if estimate["estimated_cost_usd"] > args.max_cost_usd:
        print(f"error: worst-case cost estimate ${estimate['estimated_cost_usd']:.2f} exceeds the "
              f"${args.max_cost_usd:.2f} cap; nothing was spent (raise --max-cost-usd or lower --runs)",
              file=sys.stderr)
        return 2
    try:
        import anthropic  # noqa: F401
    except ImportError as exc:
        print(f"error: anthropic SDK not importable ({exc}); run via `uv run --with anthropic python3 ...`",
              file=sys.stderr)
        return 2
    if not key:
        print("error: no Anthropic credentials -- ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN) is not set",
              file=sys.stderr)
        return 2
    print(f"  credential present ({len(key)} bytes); worst-case estimate ${estimate['estimated_cost_usd']:.2f}")
    t0 = time.time()
    rc = run(args.runs, args.workers, output, receipt, args.max_cost_usd)
    print(f"  elapsed {time.time() - t0:.0f}s; spent ${actual_cost_usd(MODEL, USAGE):.2f} "
          f"over {USAGE['calls']} calls")
    return rc


if __name__ == "__main__":
    sys.exit(main())
