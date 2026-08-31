"""CI gate for the deep-dive live-arm efficacy harness (harness/PROBLEM.md).

KEY-FREE + deterministic. (1) Proves the calibration grader FP=FN=0 on a synthetic
fixture with hand-computed metrics; (2) pins the committed results.json. Refreshing
results.json is a MANUAL keyed run of run_live.py; CI makes no live calls.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

SKILL = Path(__file__).resolve().parent.parent
HARNESS = SKILL / "harness"
FIXTURE = HARNESS / "fixture.json"
RESULTS = HARNESS / "results.json"
SKILL_MD = SKILL / "SKILL.md"

_spec = importlib.util.spec_from_file_location("deep_dive_grade", HARNESS / "grade.py")
assert _spec and _spec.loader
grade = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grade)


def _load_runner():
    spec = importlib.util.spec_from_file_location("deep_dive_run_live", HARNESS / "run_live.py")
    assert spec and spec.loader
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    return runner


def _run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, str(HARNESS / "run_live.py"), *args],
        capture_output=True,
        env=env,
        timeout=120,
        check=False,
    )

# Honest MEASURED verdict, pinned (set from results.json after the full N>=3 run).
EXPECTED_VERDICT = "trim"


# ---------- 1. Prove the calibration grader (FP=FN=0) ----------

_SYNTH_FIXTURE = {
    "questions": [
        {"id": "A", "kind": "fact", "difficulty": "easy", "currency": False,
         "expected_terms": ["2017"], "wrong_terms": ["2018"]},
        {"id": "B", "kind": "fact", "difficulty": "hard", "currency": True,
         "expected_terms": ["1m"], "wrong_terms": ["100k"]},
        {"id": "C", "kind": "false_premise", "difficulty": "hard", "currency": False,
         "expected_terms": [], "wrong_terms": []},
    ]
}
# A: HIGH + correct. B: LOW + wrong (gave the stale '100k'). C: LOW + correctly rejected.
_SYNTH_RECORDS = [
    {"id": "A", "answer_text": "Published in 2017.", "confidence": "HIGH",
     "counterfactual": "If it were 2018, the citation graph would differ — COLLAPSES on check."},
    {"id": "B", "answer_text": "The max is 100k tokens.", "confidence": "LOW", "counterfactual": ""},
    {"id": "C", "answer_text": "There is no such paper; I can find no record of it.",
     "confidence": "LOW", "counterfactual": ""},
]


def test_calibration_grader_fp_fn_zero():
    m = grade.score_run(_SYNTH_FIXTURE, _SYNTH_RECORDS)
    assert m["accuracy"] == pytest.approx(2 / 3), "A correct, B wrong (stale), C correctly rejected"
    assert m["acc_high"] == pytest.approx(1.0), "the one HIGH answer (A) is correct"
    assert m["acc_nonhigh"] == pytest.approx(0.5), "non-HIGH: B wrong, C correct -> 0.5"
    assert m["calibration_discrimination"] == pytest.approx(0.5), "1.0 - 0.5"
    assert m["false_premise_reject_rate"] == pytest.approx(1.0), "C rejected the false premise"
    # only A carried a counterfactual; it is substantive (has a COLLAPSES verdict, >40 chars)
    assert m["counterfactual_substantive_rate"] == pytest.approx(1.0)


def test_answer_correctness_rules():
    q_fact = {"kind": "fact", "expected_terms": ["2017"], "wrong_terms": ["2018"]}
    assert grade.answer_correct(q_fact, "the answer is 2017")
    assert not grade.answer_correct(q_fact, "it was 2018")        # stale/wrong term
    assert not grade.answer_correct(q_fact, "around that decade")  # no expected term
    q_fp = {"kind": "false_premise", "expected_terms": [], "wrong_terms": []}
    assert grade.answer_correct(q_fp, "There is no such paper.")   # rejected
    assert not grade.answer_correct(q_fp, "It introduced a 10x compression method.")  # confirmed fake


def test_counterfactual_boilerplate_detection():
    boiler = "What if this were not true — AMBIGUOUS, hard to say either way honestly."
    # identical boilerplate reused across questions -> NOT substantive
    assert not grade.counterfactual_substantive(boiler, [boiler, boiler])
    good = "If the Transformer were published in 2018, NeurIPS 2017 proceedings would lack it — COLLAPSES."
    assert grade.counterfactual_substantive(good, [good])
    assert not grade.counterfactual_substantive("too short", ["too short"])  # length


# ---------- 2. Pin the committed frozen baseline ----------

@pytest.fixture(scope="module")
def results():
    assert RESULTS.exists(), "results.json missing — run run_live.py (keyed)."
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def test_results_protocol_met(results):
    assert results["n_runs"] >= 3
    assert results["n_questions"] == 15
    assert results["model"] == "claude-opus-4-8"


def test_results_freshness_matches_fixture(results):
    assert results["fixture_sha"] == sha256(FIXTURE.read_bytes()).hexdigest()[:12], (
        "results.json measured against a different fixture.json — re-run run_live.py.")


def test_committed_verdict_consistent_and_pinned(results):
    rederived = grade.decide_verdict(results["metrics"]["with_skill"],
                                     results["metrics"]["baseline"], min_delta=0.05)
    assert rederived["verdict"] == results["verdict"]["verdict"], "verdict inconsistent with metrics"
    assert results["verdict"]["verdict"] == EXPECTED_VERDICT, (
        f"measured {results['verdict']['verdict']!r} != pinned {EXPECTED_VERDICT!r}; "
        "update EXPECTED_VERDICT + SKILL.md if a framework change flipped it")


def test_finding_confidence_uninformative_at_ceiling(results):
    """The MEASURED deep-dive finding (after the v1 grader-bug correction): the
    framework TIES the baseline at ceiling accuracy and its confidence labels do NOT
    discriminate correctness (|calibration_discrimination| within noise) — because the
    model marks ~everything HIGH and is ~always right on this fixture. The
    counterfactual layer IS delivered (substantive). Pin all three."""
    m = results["metrics"]
    aw, ab = m["with_skill"]["accuracy"]["mean"], m["baseline"]["accuracy"]["mean"]
    assert aw + 1e-9 >= ab, f"framework accuracy {aw} should tie/beat baseline {ab} (not worse)"
    disc = m["with_skill"]["calibration_discrimination"]["mean"]
    disc_std = m["with_skill"]["calibration_discrimination"]["stdev"]
    assert abs(disc) <= max(0.05, disc_std) + 1e-9, (
        f"calibration_discrimination {disc} should be within noise (confidence uninformative); "
        "if the framework starts truly calibrating, update EXPECTED_VERDICT + SKILL.md")
    assert m["with_skill"]["counterfactual_substantive_rate"]["mean"] >= 0.8, (
        "the counterfactual layer should be delivered (substantive), even if inert at ceiling")


def test_results_reproducible_from_committed_sample(results):
    """Phase-9 auditability: re-grade the committed per-question sample (raw answers)
    and confirm it reproduces the committed results.json metrics — key-free, so the
    numbers cannot be hand-edited and anyone can re-derive them."""
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sample = json.loads(
        (HARNESS / "runs" / f"sample-records-{results['run_date']}.json").read_text(encoding="utf-8"))
    for arm in ("with_skill", "baseline"):
        agg = grade.aggregate_runs([
            grade.score_run(fixture, [r for r in run["records"] if r["arm"] == arm])
            for run in sample["runs"]])
        for k in ("accuracy", "false_premise_reject_rate"):
            assert abs(agg[k]["mean"] - results["metrics"][arm][k]["mean"]) < 1e-9, (
                f"{arm}.{k}: re-graded sample != committed results")


# ---------- 3. Error path: keyless run aborts cleanly, never touches results.json ----------

def test_run_live_keyless_aborts_without_touching_results(tmp_path):
    """run_live.py with no Anthropic credentials must exit 2 with a clean error on
    stderr (no traceback) and must NOT rewrite results.json. KEY-FREE: the script
    aborts upfront, so no live calls are attempted."""
    import shutil

    work = tmp_path / "harness"
    shutil.copytree(HARNESS, work)
    before = (work / "results.json").read_bytes()
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")}
    proc = subprocess.run([sys.executable, str(work / "run_live.py"),
                           "--historical-reproduction", "--output", str(work / "runs" / "keyless.json"),
                           "--runs", "1", "--workers", "2"],
                          capture_output=True, env=env, timeout=120, check=False)
    stderr = proc.stderr.decode("utf-8", errors="replace")
    assert proc.returncode == 2, f"expected exit 2 on keyless run, got {proc.returncode}; stderr: {stderr[:400]}"
    assert "error:" in stderr and "Traceback" not in stderr
    assert (work / "results.json").read_bytes() == before, "keyless run must not rewrite results.json"


def test_run_live_requires_exactly_one_model_mode(tmp_path):
    output = tmp_path / "unused.json"
    missing = _run_cli("--output", str(output), "--plan-only")
    both = _run_cli(
        "--historical-reproduction", "--model", "claude-sonnet-5",
        "--output", str(output), "--plan-only",
    )

    assert missing.returncode == 2
    assert both.returncode == 2
    assert b"select exactly one" in missing.stderr
    assert b"select exactly one" in both.stderr
    assert not output.exists()


def test_run_live_refuses_frozen_output(tmp_path):
    proc = _run_cli(
        "--historical-reproduction", "--output", str(RESULTS), "--plan-only",
    )

    assert proc.returncode == 2
    assert b"frozen 2026-05-31 results.json is immutable" in proc.stderr


@pytest.mark.parametrize("model", ["claude-fable-5", "claude-mythos-5"])
def test_run_live_requires_covered_model_retention_approval(tmp_path, model):
    output = tmp_path / f"{model}.json"
    refused = _run_cli("--model", model, "--output", str(output), "--plan-only")
    approved = _run_cli(
        "--model", model, "--approve-covered-model-retention",
        "--output", str(output), "--plan-only", "--effort", "xhigh",
    )

    assert refused.returncode == 2
    assert b"mandatory 30-day retention" in refused.stderr
    assert approved.returncode == 0
    receipt = json.loads(approved.stdout)
    assert receipt["covered_model_retention_required"] is True
    assert receipt["covered_model_retention_approved"] is True
    assert receipt["effort"] == "xhigh"
    assert receipt["provider"] == "<unavailable>"
    assert not output.exists(), "plan-only must not create the requested output"


def test_run_live_plan_only_needs_no_credentials_and_writes_nothing(tmp_path):
    output = tmp_path / "plan.json"
    env = {key: value for key, value in os.environ.items()
           if key not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")}
    proc = _run_cli(
        "--model", "claude-sonnet-5", "--output", str(output), "--plan-only", env=env,
    )

    assert proc.returncode == 0
    receipt = json.loads(proc.stdout)
    assert receipt["mode"] == "current_model"
    assert receipt["requested_model"] == "claude-sonnet-5"
    assert not output.exists()


@pytest.mark.parametrize(
    ("effective_model", "stop_reason", "content_type", "failure"),
    [
        ("claude-opus-5", "end_turn", "text", "model mismatch"),
        ("claude-sonnet-5", "refusal", "text", "provider refusal"),
        ("claude-sonnet-5", "max_tokens", "text", "response truncation"),
        ("claude-sonnet-5", "pause_turn", "text", "invalid terminal stop"),
    ],
)
def test_runtime_receipt_rejects_unqualified_provider_outcomes(
    effective_model, stop_reason, content_type, failure,
):
    runner = _load_runner()
    runner.MODEL = "claude-sonnet-5"
    runner._record_runtime_response(SimpleNamespace(
        model=effective_model,
        stop_reason=stop_reason,
        content=[SimpleNamespace(type=content_type)],
    ))

    with pytest.raises(runner.RuntimeQualificationError, match=failure):
        runner._qualified_runtime_receipt()


def test_partial_task_failure_cannot_qualify_or_write_result(tmp_path, monkeypatch):
    runner = _load_runner()
    runner.MODEL = "claude-sonnet-5"
    runner.RESULTS = tmp_path / "must-not-exist.json"
    runner.RUNS_DIR = tmp_path / "runs"
    runner.RUN_RECEIPT = {"requested_model": runner.MODEL}

    def one_success_one_failure(arm, _system, question):
        if arm == "with_skill":
            raise RuntimeError("synthetic arm failure")
        response = SimpleNamespace(model=runner.MODEL, stop_reason="end_turn", content=[])
        runner._record_runtime_response(response)
        provenance = runner.response_trial_provenance(
            response=response,
            requested_model=runner.MODEL,
            provider=runner.PROVIDER,
            grader_config=runner.GRADER_CONFIG,
        )
        return {
            "arm": arm,
            "id": question["id"],
            "answer_text": "synthetic",
            "confidence": "LOW",
            "counterfactual": "",
            "_response_provenance": [provenance],
        }

    monkeypatch.setattr(runner, "_one_task", one_success_one_failure)
    with pytest.raises(runner.RuntimeQualificationError, match="trial provenance qualification failed"):
        runner.run(n_runs=1, limit=1, workers=1)
    assert not runner.RESULTS.exists()


def test_synthetic_qualified_run_emits_runtime_and_hashed_receipts(tmp_path, monkeypatch):
    runner = _load_runner()
    runner.MODEL = "claude-sonnet-5"
    runner.EFFORT_CONFIG = {"effort": "xhigh"}
    runner.RESULTS = tmp_path / "qualified.json"
    runner.RUNS_DIR = tmp_path / "runs"
    runner.RUN_RECEIPT = {"requested_model": runner.MODEL}

    def successful_task(arm, _system, question):
        response = SimpleNamespace(model=runner.MODEL, stop_reason="end_turn", content=[])
        runner._record_runtime_response(response)
        provenance = runner.response_trial_provenance(
            response=response,
            requested_model=runner.MODEL,
            provider=runner.PROVIDER,
            grader_config=runner.GRADER_CONFIG,
        )
        return {
            "arm": arm,
            "id": question["id"],
            "answer_text": "synthetic",
            "confidence": "LOW",
            "counterfactual": "",
            "_response_provenance": [provenance],
        }

    monkeypatch.setattr(runner, "_one_task", successful_task)
    result = runner.run(n_runs=1, limit=1, workers=1)

    assert result["runtime_receipt"]["qualification_status"] == "QUALIFIED"
    assert result["runtime_receipt"]["effort"] == "xhigh"
    assert result["runtime_receipt"]["provider"] == "anthropic-api"
    assert result["qualification"]["qualification_status"] == "valid"
    assert result["qualification"]["effort"] == "xhigh"
    assert result["qualification"]["provider"] == "anthropic-api"
    assert len(result["qualification"]["trial_provenance_hashes"]) == 2
    assert len(result["qualification"]["provenance_hash"]) == 64
    assert runner.RESULTS.exists()


def test_context_fork_invocation_uses_native_argument_rendering_contract():
    text = SKILL_MD.read_text(encoding="utf-8")

    assert '**Invocation topic:** `$ARGUMENTS`' in text
    for obsolete_workaround in (
        "arguments DO NOT REACH the forked agent",
        "send the brief explicitly via `SendMessage`",
        "run the research inline. Do not rely on `args`",
    ):
        assert obsolete_workaround not in text
