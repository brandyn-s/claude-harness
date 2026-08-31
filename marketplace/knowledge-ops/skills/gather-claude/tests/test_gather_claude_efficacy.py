"""CI gate for the gather-claude live-arm efficacy harness (harness/PROBLEM.md).

KEY-FREE + deterministic. (1) Proves the grader instrument FP=FN=0 on a synthetic
fixture; (2) pins the committed results.json (schema, N>=3, freshness, verdict).
Refreshing results.json is a MANUAL keyed run of run_live.py; CI makes no live calls.
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

# Unique module name to avoid sys.modules collision under `pytest skills/`.
_spec = importlib.util.spec_from_file_location("gather_claude_grade", HARNESS / "grade.py")
assert _spec and _spec.loader
grade = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grade)

# Honest MEASURED verdict, pinned (set from results.json after the full N>=3 run).
# 2026-05-31: was "fix" (true_recall regression). After the calibration-floor fix +
# re-measurement, the regression is eliminated and the framework leads on the robust
# primary (verdict_accuracy) -> "keep". See PROBLEM.md §5/§6.
EXPECTED_VERDICT = "keep"


# ---------- 1. Prove the grader instrument (FP=FN=0) ----------

_SYNTH_FIXTURE = {
    "claims": [
        {"id": "A", "category": "true_primary", "expected_disposition": "supported",
         "grounding_terms": ["alpha", "beta"]},
        {"id": "B", "category": "fabricated", "expected_disposition": "not_supported",
         "grounding_terms": ["nonexistent-field", "fake-flag"]},
        {"id": "C", "category": "outdated", "expected_disposition": "not_supported",
         "grounding_terms": ["gamma"]},
    ]
}
_SYNTH_RECORDS = [
    {"id": "A", "raw_verdict": "SUPPORTED", "cited_urls": ["u"], "grounded": True},
    {"id": "B", "raw_verdict": "SUPPORTED", "cited_urls": ["u"], "grounded": False},
    {"id": "C", "raw_verdict": "OUTDATED", "cited_urls": [], "grounded": None},
]


def test_grader_instrument_fp_fn_zero():
    m = grade.score_run(_SYNTH_FIXTURE, _SYNTH_RECORDS)
    assert m["grounding_precision"] == pytest.approx(0.5)
    assert m["refutation_recall"] == pytest.approx(1.0)   # C (outdated) downgraded
    assert m["fabrication_resistance"] == pytest.approx(0.0)  # B wrongly SUPPORTED
    assert m["true_recall"] == pytest.approx(1.0)
    assert m["verdict_accuracy"] == pytest.approx(2 / 3)


def test_normalize_verdict_handles_currency_vocab():
    # The arms emit constrained enums (run_live.py): WITH = SUPPORTED/REFUTED/
    # CONTESTED/OUTDATED/UNCHARTED; BASE = TRUE/FALSE/DEPRECATED/OUTDATED/
    # NONEXISTENT. Every one must normalize to the intended disposition so the
    # baseline is never under-counted (which would inflate the framework's edge).
    for v in ["SUPPORTED", "TRUE"]:
        assert grade.normalize_verdict(v) == "supported", v
    for v in ["REFUTED", "CONTESTED", "OUTDATED", "UNCHARTED",
              "FALSE", "DEPRECATED", "NONEXISTENT"]:
        assert grade.normalize_verdict(v) == "not_supported", v


# ---------- 2. Pin the committed frozen baseline ----------

@pytest.fixture(scope="module")
def results():
    assert RESULTS.exists(), (
        "results.json missing — run `python3 skills/gather-claude/harness/run_live.py` (keyed).")
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def test_results_protocol_met(results):
    assert results["n_runs"] >= 3
    assert results["n_claims"] == 15
    assert results["model"] == "claude-opus-4-8"


def test_results_freshness_matches_fixture(results):
    assert results["fixture_sha"] == sha256(FIXTURE.read_bytes()).hexdigest()[:12], (
        "results.json measured against a different fixture.json — re-run run_live.py.")


def test_both_arms_have_all_metrics(results):
    for arm in ("with_skill", "baseline"):
        m = results["metrics"][arm]
        for k in ("grounding_precision", "refutation_recall", "fabrication_resistance",
                  "true_recall", "verdict_accuracy"):
            assert m.get(k) is not None and "mean" in m[k], f"{arm}.{k} missing"


def test_committed_verdict_consistent_and_pinned(results):
    rederived = grade.decide_verdict(
        results["metrics"]["with_skill"], results["metrics"]["baseline"],
        results["primary_metric"], results["cost_ratio"], min_delta=0.05)
    assert rederived["verdict"] == results["verdict"]["verdict"], "verdict inconsistent with metrics"
    assert results["verdict"]["verdict"] == EXPECTED_VERDICT, (
        f"measured {results['verdict']['verdict']!r} != pinned {EXPECTED_VERDICT!r}; "
        "if a framework change flipped it, update EXPECTED_VERDICT + SKILL.md")


def test_calibration_fix_eliminated_overrejection_and_framework_now_leads(results):
    """Post-calibration-fix MEASURED finding (the pinned reality, 2026-05-31).
    Pre-fix this skill's framework over-rejected current features (true_recall
    -0.20 vs baseline -> the `fix` verdict). After relaxing the over-conservative
    UNCHARTED rule (uncharted-vs-refuted.md) + re-measuring, the regression is
    ELIMINATED (with_skill true_recall now >= baseline) AND the framework leads on
    overall verdict_accuracy, WITHOUT leaking fabrication-resistance. Pinned with
    equal specificity to the prior regression-finding so that a returning
    regression — or a calibration floor that starts accepting fabricated features —
    visibly fails this and the verdict."""
    m = results["metrics"]
    w_tr, b_tr = m["with_skill"]["true_recall"]["mean"], m["baseline"]["true_recall"]["mean"]
    assert w_tr >= b_tr, (
        f"true_recall over-rejection returned: with_skill {w_tr} < baseline {b_tr} "
        f"(the calibration fix must keep with_skill >= baseline)")
    w_va, b_va = m["with_skill"]["verdict_accuracy"]["mean"], m["baseline"]["verdict_accuracy"]["mean"]
    assert w_va > b_va, (
        f"framework no longer leads verdict_accuracy ({w_va} vs {b_va}); "
        f"the `keep` verdict depends on this lead — update EXPECTED_VERDICT + SKILL.md")
    assert m["with_skill"]["fabrication_resistance"]["mean"] == 1.0, (
        "calibration floor leaked: with_skill now accepts fabricated features")


def test_results_reproducible_from_committed_sample(results):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sample_path = HARNESS / "runs" / "sample-records-2026-05-31.json"
    assert sample_path.exists(), "committed re-gradeable sample missing"
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    for arm in ("with_skill", "baseline"):
        agg = grade.aggregate_runs([
            grade.score_run(fixture, [r for r in run["records"] if r["arm"] == arm])
            for run in sample["runs"]])
        for k in ("grounding_precision", "refutation_recall", "fabrication_resistance",
                  "true_recall", "verdict_accuracy"):
            assert abs(agg[k]["mean"] - results["metrics"][arm][k]["mean"]) < 1e-9, (
                f"{arm}.{k}: re-graded sample != committed results")
