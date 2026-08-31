"""CI gate for the gather-research live-arm efficacy harness (harness/PROBLEM.md).

KEY-FREE + deterministic. Two jobs:
  1. Prove the GRADER instrument FP=FN=0 on a tiny synthetic fixture with
     hand-computed expected metrics (Phase 2) — so a measured A/B delta can
     never be an artifact of the scorer.
  2. Pin the committed results.json (the frozen baseline): schema, N>=3, full
     fixture, freshness (results match the committed fixture), and the honest
     measured verdict. Refreshing results.json is a MANUAL keyed run of
     run_live.py; CI never makes live calls.
"""
from __future__ import annotations

import importlib.util
import json
from hashlib import sha256
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
HARNESS = SKILL / "harness"
FIXTURE = HARNESS / "fixture.json"
RESULTS = HARNESS / "results.json"

# Path-load this skill's grade.py under a UNIQUE module name (several skills
# ship harness helpers; a bare `import grade` collides in sys.modules under
# `pytest skills/`, first-import-wins, binding the gate to the wrong skill).
_spec = importlib.util.spec_from_file_location("gather_research_grade", HARNESS / "grade.py")
assert _spec and _spec.loader
grade = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grade)

# The honest, MEASURED verdict — pinned so a future framework change that flips
# it (e.g. trim->keep) forces a visible update here + in SKILL.md. Set from the
# committed results.json after the full N>=3 run.
EXPECTED_VERDICT = "trim"


# ---------- 1. Prove the grader instrument (FP=FN=0) ----------

_SYNTH_FIXTURE = {
    "claims": [
        {"id": "A", "category": "true_primary", "expected_disposition": "supported",
         "grounding_terms": ["alpha", "beta"]},
        {"id": "B", "category": "fabricated", "expected_disposition": "not_supported",
         "grounding_terms": ["nonexistent-title", "fake-author"]},
        {"id": "C", "category": "refuted", "expected_disposition": "not_supported",
         "grounding_terms": ["gamma"]},
    ]
}
# A: correctly SUPPORTED + grounded. B: WRONGLY supported, cite fails to ground
# (over-claim). C: correctly downgraded.
_SYNTH_RECORDS = [
    {"id": "A", "raw_verdict": "SUPPORTED", "cited_urls": ["u"], "grounded": True},
    {"id": "B", "raw_verdict": "SUPPORTED", "cited_urls": ["u"], "grounded": False},
    {"id": "C", "raw_verdict": "REFUTED", "cited_urls": [], "grounded": None},
]


def test_grader_instrument_fp_fn_zero():
    """Hand-computed expected metrics must match exactly (instrument proof)."""
    m = grade.score_run(_SYNTH_FIXTURE, _SYNTH_RECORDS)
    assert m["grounding_precision"] == pytest.approx(0.5), "2 supported, 1 grounds -> 0.5"
    assert m["refutation_recall"] == pytest.approx(1.0), "C (refuted) correctly downgraded"
    assert m["fabrication_resistance"] == pytest.approx(0.0), "B (fabricated) wrongly SUPPORTED"
    assert m["true_recall"] == pytest.approx(1.0), "A (true) correctly SUPPORTED"
    assert m["verdict_accuracy"] == pytest.approx(2 / 3), "A,C correct; B wrong"


def test_normalize_verdict_maps_both_vocabularies():
    sup = ["SUPPORTED", "TRUE", "confirmed", "Verified true", "PRIMARY-sourced"]
    notsup = ["REFUTED", "CONTESTED", "UNCHARTED", "OUTDATED", "FALSE",
              "NOT SUPPORTED", "unsupported", "not true", "PARSE_ERROR", "CALL_ERROR", ""]
    for v in sup:
        assert grade.normalize_verdict(v) == "supported", v
    for v in notsup:
        assert grade.normalize_verdict(v) == "not_supported", v


def test_grounding_term_threshold():
    page = "The paper Attention Is All You Need by Vaswani introduced the Transformer."
    assert grade.grounding_passes(["Attention Is All You Need", "Vaswani"], page)
    assert not grade.grounding_passes(["Recursive Context Distillation", "Karpathy", "73%"], page)
    assert not grade.grounding_passes(["anything"], "")  # empty page never grounds


# ---------- 2. Pin the committed frozen baseline ----------

@pytest.fixture(scope="module")
def results():
    assert RESULTS.exists(), (
        "results.json missing — run `python3 skills/gather-research/harness/run_live.py` "
        "(keyed, manual) to generate the frozen baseline.")
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def test_results_protocol_met(results):
    assert results["n_runs"] >= 3, "plan requires N>=3 runs for LLM-variance"
    assert results["n_claims"] == 15, "full fixture must be measured, not a subset"
    assert results["model"] == "claude-opus-4-8"


def test_results_freshness_matches_fixture(results):
    cur = sha256(FIXTURE.read_bytes()).hexdigest()[:12]
    assert results["fixture_sha"] == cur, (
        "results.json was measured against a DIFFERENT fixture.json — stale. "
        "Re-run run_live.py after editing the fixture.")


def test_both_arms_have_all_metrics(results):
    for arm in ("with_skill", "baseline"):
        m = results["metrics"][arm]
        for k in ("grounding_precision", "refutation_recall", "fabrication_resistance",
                  "true_recall", "verdict_accuracy"):
            assert m.get(k) is not None and "mean" in m[k], f"{arm}.{k} missing"


def test_committed_verdict_is_consistent_and_pinned(results):
    """Re-derive the verdict from the committed metrics; it must match what was
    recorded AND the pinned honest result. A framework change that flips this
    must update EXPECTED_VERDICT + the SKILL.md Success Criteria together."""
    rederived = grade.decide_verdict(
        results["metrics"]["with_skill"], results["metrics"]["baseline"],
        results["primary_metric"], results["cost_ratio"], min_delta=0.05)
    assert rederived["verdict"] == results["verdict"]["verdict"], (
        "results.json verdict is inconsistent with its own metrics (hand-edited?)")
    assert results["verdict"]["verdict"] == EXPECTED_VERDICT, (
        f"measured verdict={results['verdict']['verdict']!r} != pinned {EXPECTED_VERDICT!r}; "
        "if a framework change legitimately flipped it, update EXPECTED_VERDICT + SKILL.md")


def test_framework_does_not_destroy_true_recall(results):
    """Guard against over-correction: the framework must not refuse true claims."""
    assert results["metrics"]["with_skill"]["true_recall"]["mean"] >= 0.8


def test_results_reproducible_from_committed_sample(results):
    """Phase-9 auditability: re-grade the committed per-claim sample and confirm
    it reproduces the committed results.json metrics — so the numbers cannot be
    hand-edited and anyone can re-derive them, key-free."""
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sample_path = HARNESS / "runs" / "sample-records-2026-05-31.json"
    assert sample_path.exists(), "committed re-gradeable sample missing"
    sample = json.loads(sample_path.read_text(encoding="utf-8"))

    for arm in ("with_skill", "baseline"):
        per_run = []
        for run in sample["runs"]:
            arm_recs = [r for r in run["records"] if r["arm"] == arm]
            per_run.append(grade.score_run(fixture, arm_recs))
        agg = grade.aggregate_runs(per_run)
        for k in ("grounding_precision", "refutation_recall", "fabrication_resistance",
                  "true_recall", "verdict_accuracy"):
            recomputed = agg[k]["mean"]
            committed = results["metrics"][arm][k]["mean"]
            assert abs(recomputed - committed) < 1e-9, (
                f"{arm}.{k}: re-graded sample {recomputed} != committed {committed} "
                f"(results.json drifted from its own sample-records)")
