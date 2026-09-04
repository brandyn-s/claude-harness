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

# A run's recorded vendor model list (run_live.fetch_model_catalog shape), newest first.
_SYNTH_CATALOG = [
    {"id": "claude-synthetic-9", "display_name": "Claude Synthetic 9", "created_at": "2026-08-01T00:00:00+00:00"},
    {"id": "claude-synthetic-8", "display_name": "Claude Synthetic 8", "created_at": "2026-05-01T00:00:00+00:00"},
]


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
    # 2026-09-03 revision: calibration is computed over FACT rows only, so the non-HIGH
    # bin is {B wrong} -> 0.0 and discrimination is 1.0. The legacy all-kinds view still
    # counts C's LOW-but-correct rejection ({B wrong, C right} -> 0.5, discrimination 0.5).
    assert m["acc_nonhigh"] == pytest.approx(0.0), "non-HIGH FACT answers: B wrong -> 0.0"
    assert m["calibration_discrimination"] == pytest.approx(1.0), "1.0 - 0.0 over fact rows"
    assert m["calibration_discrimination_all"] == pytest.approx(0.5), "legacy view: 1.0 - 0.5"
    assert m["n_key_expired"] == 0
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


# ---------- 1b. 2026-09-03 grader revision (docs/research-skills-root-cause.md section 4) ----------

_FIXTURE = json.loads(FIXTURE.read_text(encoding="utf-8"))


def _question(qid: str) -> dict:
    return next(q for q in _FIXTURE["questions"] if q["id"] == qid)


# Verbatim openings of the four correct rejections of `cot-faithfulness-solved` that the v1
# cue list false-failed on 2026-09-03 (deep-dive/2026-09-03/run0/with_skill and run0-2/baseline).
_OBSERVED_REJECTIONS_2026_09_03 = (
    ("None. No 2025 result definitively solved chain-of-thought faithfulness or guaranteed that CoT "
     "always reflects a model's true reasoning; the premise is false. The 2025 literature documented "
     "the opposite: Arcuschin et al. found unfaithfulness on natural, non-adversarial prompts."),
    ("None. No 2025 result solved chain-of-thought faithfulness or guaranteed that CoT always reflects "
     "a model's true reasoning — the premise is false."),
    ("None. No 2025 result 'definitively solved' chain-of-thought faithfulness — the question's premise "
     "is false. In fact, 2025 research largely demonstrated the opposite."),
    ("None. No 2025 result definitively solved chain-of-thought faithfulness. The question's premise is "
     "false. CoT faithfulness remains an open research problem as of 2026."),
)


def test_rejection_cues_cover_observed_2026_09_03_phrasings():
    q_fp = {"kind": "false_premise", "expected_terms": [], "wrong_terms": []}
    for text in _OBSERVED_REJECTIONS_2026_09_03:
        assert grade.answer_correct(q_fp, text) is True, text[:60]
    # each added cue fires on its own
    for cue_text in ("the premise is false", "faithfulness remains unsolved", "it is an open problem",
                     "no such result exists", "the premise of the question is false"):
        assert grade.rejects_premise(f"Short answer: {cue_text}."), cue_text
    # the leading-negation rule is deliberately narrow
    assert grade.rejects_premise("None. It was never solved.")
    assert grade.rejects_premise("No such paper exists.")
    assert not grade.rejects_premise("Novel approaches introduced a 10x compression method in 2025.")
    assert not grade.rejects_premise("No, but the closest is the 10x method the paper introduced.")
    # a confirmation of the fake specific still fails
    assert grade.answer_correct(q_fp, "It introduced a 10x compression method now standard in production.") is False


def test_dated_keys_select_by_run_date():
    q = _question("current-anthropic-model")
    opus = "As of mid-2026, Anthropic's most capable Claude family is Opus, with Claude Opus 4.8 as the flagship."
    fable = "The Mythos-class tier — Claude Fable 5 / Claude Mythos 5 — sits above Opus, Sonnet and Haiku."
    assert grade.answer_correct(q, opus, run_date="2026-05-31") is True
    assert grade.answer_correct(q, fable, run_date="2026-05-31") is False
    assert grade.answer_correct(q, fable, run_date="2026-09-03") is True
    assert grade.answer_correct(q, opus, run_date="2026-09-03") is False
    # window edges are inclusive
    assert grade.key_for(q, "2026-06-08")["verified"] == "2026-05-31"
    assert grade.key_for(q, "2026-06-09")["verified"] is None, "the Fable-era key is inferred, not hand-verified"
    # dated keys must never grade silently without a run date
    with pytest.raises(ValueError, match="run_date"):
        grade.answer_correct(q, opus)
    with pytest.raises(ValueError, match="run_date"):
        grade.score_run(_FIXTURE, [{"id": q["id"], "answer_text": opus, "confidence": "HIGH"}])
    # questions without `keys` ignore run_date
    stable = _question("transformer-year")
    assert grade.answer_correct(stable, "Published in 2017.", run_date="2031-01-01") is True


def test_expired_key_excludes_question_instead_of_grading_stale():
    fixture = {"questions": [
        {"id": "cur", "kind": "fact", "currency": True,
         "keys": [{"valid_from": None, "valid_until": "2026-06-08", "expected_terms": ["opus 4"], "wrong_terms": []}]},
        {"id": "stable", "kind": "fact", "currency": False, "expected_terms": ["2017"], "wrong_terms": []},
    ]}
    recs = [{"id": "cur", "answer_text": "Claude Fable 5", "confidence": "HIGH"},
            {"id": "stable", "answer_text": "2017", "confidence": "HIGH"}]
    m = grade.score_run(fixture, recs, run_date="2026-09-03")
    assert m["n_key_expired"] == 1 and m["key_expired_ids"] == ["cur"]
    assert m["n_scored"] == 1
    assert m["accuracy"] == pytest.approx(1.0), "an expired key EXCLUDES the question; it is not scored wrong"
    assert m["currency_accuracy"] is None, "no scorable currency question left"
    assert grade.answer_correct(fixture["questions"][0], "Claude Fable 5", run_date="2026-09-03") is None
    m_old = grade.score_run(fixture, recs, run_date="2026-05-31")
    assert m_old["n_key_expired"] == 0 and m_old["accuracy"] == pytest.approx(0.5)


def test_calibration_discrimination_over_fact_questions_only():
    fixture = {"questions": [
        {"id": "f1", "kind": "fact", "expected_terms": ["alpha"], "wrong_terms": []},
        {"id": "f2", "kind": "fact", "expected_terms": ["beta"], "wrong_terms": []},
        {"id": "fp", "kind": "false_premise", "expected_terms": [], "wrong_terms": []},
    ]}
    recs = [{"id": "f1", "answer_text": "alpha", "confidence": "HIGH"},
            {"id": "f2", "answer_text": "wrong", "confidence": "LOW"},
            {"id": "fp", "answer_text": "No such paper exists.", "confidence": "LOW"}]
    m = grade.score_run(fixture, recs)
    assert m["calibration_discrimination"] == pytest.approx(1.0), "fact rows: HIGH 1/1 vs non-HIGH 0/1"
    assert m["calibration_discrimination_all"] == pytest.approx(0.5), "legacy view counted the LOW-but-correct rejection"
    # the measured 2026-09-03 shape: every non-HIGH label sits on a correct rejection (the framework
    # obeying "LOW when the premise is dubious") -> no anti-calibration signal, not a `fix`
    recs2 = [{"id": "f1", "answer_text": "alpha", "confidence": "HIGH"},
             {"id": "f2", "answer_text": "beta", "confidence": "HIGH"},
             {"id": "fp", "answer_text": "No such paper exists.", "confidence": "LOW"}]
    m2 = grade.score_run(fixture, recs2)
    assert m2["calibration_discrimination"] is None, "no non-HIGH fact row: nothing to discriminate"
    assert m2["calibration_discrimination_all"] == pytest.approx(0.0)


def test_fixture_revision_lineage_records_the_frozen_sha():
    revisions = _FIXTURE.get("_revisions", [])
    assert revisions, "fixture.json was revised after the freeze; it must carry a `_revisions` lineage"
    assert revisions[0]["supersedes_sha"] == "7ffac4dca15f", "the frozen results.json was measured against 7ffac4dca15f"
    for rev in revisions:
        assert rev["date"] and rev["change"] and rev["supersedes_sha"]


def _run_regrade(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(HARNESS / "regrade.py"), *args],
                          capture_output=True, text=True, timeout=120, check=False)


def _assert_same_mean(a, b, label: str) -> None:
    if a is None or b is None:
        assert a == b, f"{label}: presence mismatch ({a!r} vs {b!r})"
    else:
        assert abs(a["mean"] - b["mean"]) < 1e-9, f"{label}: {a['mean']} != {b['mean']}"


def test_regrade_tool_reproduces_frozen_baseline_from_committed_sample(results, tmp_path):
    """The corrected grader + regrade.py re-derive the frozen 2026-05-31 numbers from the
    committed sample on every metric (no API calls), so the revision changed nothing about
    the frozen measurement."""
    out = tmp_path / "regrade-frozen.json"
    proc = _run_regrade("--records", str(HARNESS / "runs" / f"sample-records-{results['run_date']}.json"),
                        "--run-date", results["run_date"], "--model", results["model"], "--output", str(out))
    assert proc.returncode == 0, proc.stderr
    rg = json.loads(out.read_text(encoding="utf-8"))
    for arm in ("with_skill", "baseline"):
        for k in grade._METRIC_KEYS:
            _assert_same_mean(rg["metrics"][arm][k], results["metrics"][arm][k], f"{arm}.{k}")
    # the CI-aware rule (added after the freeze) turns the frozen legacy `trim` on a zero
    # accuracy delta into BLOCKED ON MEASUREMENT; the metrics are what must match.
    assert rg["verdict"]["verdict"] == "BLOCKED ON MEASUREMENT"
    assert rg["regrade"]["fixture_sha"] == sha256(FIXTURE.read_bytes()).hexdigest()[:12]


def test_regrade_refuses_to_overwrite_frozen_results(tmp_path):
    proc = _run_regrade("--records", str(HARNESS / "runs" / "sample-records-2026-05-31.json"),
                        "--run-date", "2026-05-31", "--model", "claude-opus-4-8", "--output", str(RESULTS))
    assert proc.returncode == 2
    assert "immutable" in proc.stderr


REGRADE_2026_09_03 = HARNESS / "runs" / "regrade-2026-09-03.json"
SAMPLE_2026_09_03 = HARNESS / "runs" / "sample-records-2026-09-03.json"


def test_regrade_2026_09_03_is_reproducible_and_not_a_fix(tmp_path):
    """The offline re-grade of the 2026-09-03 Fable 5.1 rerun (docs/research-skills-root-cause.md
    section 12) re-derives from its committed compact sample, and under the corrected grader both
    arms sit at true ceiling: the live run's `fix` (anti-calibration) was an instrument artifact."""
    committed = json.loads(REGRADE_2026_09_03.read_text(encoding="utf-8"))
    assert committed["model"] == "claude-fable-5-1" and committed["run_date"] == "2026-09-03"
    out = tmp_path / "regrade.json"
    proc = _run_regrade("--records", str(SAMPLE_2026_09_03), "--run-date", committed["run_date"],
                        "--model", committed["model"], "--output", str(out))
    assert proc.returncode == 0, proc.stderr
    rg = json.loads(out.read_text(encoding="utf-8"))
    assert rg["verdict"]["verdict"] == committed["verdict"]["verdict"]
    for arm in ("with_skill", "baseline"):
        for k in grade._METRIC_KEYS + ("calibration_discrimination_all",):
            _assert_same_mean(rg["metrics"][arm][k], committed["metrics"][arm][k], f"{arm}.{k}")
    assert committed["metrics"]["with_skill"]["accuracy"]["mean"] == pytest.approx(1.0)
    assert committed["metrics"]["baseline"]["accuracy"]["mean"] == pytest.approx(1.0)
    assert committed["verdict"]["verdict"] != "fix"
    assert committed["regrade"]["fixture_sha"] == sha256(FIXTURE.read_bytes()).hexdigest()[:12]


# ---------- 2. Pin the committed frozen baseline ----------

@pytest.fixture(scope="module")
def results():
    assert RESULTS.exists(), "results.json missing — run run_live.py (keyed)."
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def test_results_protocol_met(results):
    assert results["n_runs"] >= 3
    assert results["n_questions"] == 15
    assert results["model"] == "claude-opus-4-8"


def _fixture_lineage() -> set[str]:
    """Current fixture sha plus every sha it is a documented revision of (`_revisions`)."""
    return {sha256(FIXTURE.read_bytes()).hexdigest()[:12]} | {
        r["supersedes_sha"] for r in _FIXTURE.get("_revisions", [])}


def test_results_freshness_matches_fixture(results):
    """The frozen results were measured against fixture 7ffac4dca15f. A grader/oracle
    correction may revise fixture.json WITHOUT a live re-run (results.json is immutable)
    only if it records the superseded sha in `_revisions` AND the committed sample still
    re-grades to the frozen numbers (test_results_reproducible_from_committed_sample)."""
    assert results["fixture_sha"] in _fixture_lineage(), (
        "results.json measured against a fixture.json that is not in the current fixture's "
        "revision lineage — re-run run_live.py or record the revision in fixture.json `_revisions`.")


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
            grade.score_run(fixture, [r for r in run["records"] if r["arm"] == arm],
                            run_date=results["run_date"])
            for run in sample["runs"]])
        for k in grade._METRIC_KEYS:
            _assert_same_mean(agg[k], results["metrics"][arm][k],
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
                           "--runs", "1", "--workers", "2", "--acknowledge-retired-fixture"],
                          capture_output=True, env=env, timeout=120, check=False)
    stderr = proc.stderr.decode("utf-8", errors="replace")
    assert proc.returncode == 2, f"expected exit 2 on keyless run, got {proc.returncode}; stderr: {stderr[:400]}"
    assert "error:" in stderr and "Traceback" not in stderr
    assert "pass --acknowledge-retired-fixture" not in stderr, "the acknowledged run must get past the fixture gate"
    assert (work / "results.json").read_bytes() == before, "keyless run must not rewrite results.json"


# ---------- 3b. Paused fixture (2026-09-04): a real run needs an explicit acknowledgement ----------

def test_run_live_refuses_paused_fixture_without_acknowledgement(tmp_path):
    """docs/research-skills-root-cause.md sections 4, 9.1 and 12.1: the currency keys are being
    made run-time-resolved elsewhere. Until then a real run prints the notice, refuses, and
    writes nothing."""
    import shutil

    work = tmp_path / "harness"
    shutil.copytree(HARNESS, work)
    before = (work / "results.json").read_bytes()
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")}
    proc = subprocess.run([sys.executable, str(work / "run_live.py"),
                           "--historical-reproduction", "--output", str(work / "runs" / "refused.json"),
                           "--runs", "1"],
                          capture_output=True, env=env, timeout=120, check=False)
    stderr = proc.stderr.decode("utf-8", errors="replace")
    assert proc.returncode == 2, stderr
    assert "RETIRED at this fixture" in stderr
    assert "--acknowledge-retired-fixture" in stderr and "Traceback" not in stderr
    assert not (work / "runs" / "refused.json").exists()
    assert (work / "results.json").read_bytes() == before


def test_plan_only_reports_fixture_status_without_acknowledgement(tmp_path):
    proc = _run_cli("--historical-reproduction", "--output", str(tmp_path / "plan.json"), "--plan-only")
    assert proc.returncode == 0, proc.stderr
    receipt = json.loads(proc.stdout)
    assert receipt["fixture_status"] == "retired"
    assert receipt["fixture_status_since"] == "2026-09-04"
    assert receipt["retired_fixture_acknowledged"] is False
    assert not (tmp_path / "plan.json").exists()


def test_harness_docs_record_the_retirement():
    for name in ("README.md", "PROBLEM.md"):
        text = (HARNESS / name).read_text(encoding="utf-8")
        assert "Retired at this fixture (2026-09-04)" in text, name
        assert "research-skills-root-cause.md" in text and "--acknowledge-retired-fixture" in text, name


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
        runner.run(n_runs=1, limit=1, workers=1, model_catalog=_SYNTH_CATALOG)
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
    result = runner.run(n_runs=1, limit=1, workers=1, model_catalog=_SYNTH_CATALOG)

    assert result["runtime_receipt"]["qualification_status"] == "QUALIFIED"
    assert result["runtime_receipt"]["model_catalog"] == _SYNTH_CATALOG
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
