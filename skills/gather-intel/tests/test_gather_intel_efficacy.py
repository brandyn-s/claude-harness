"""CI gate for the gather-intel live-arm efficacy harness (harness/PROBLEM.md).

KEY-FREE + deterministic. (1) Proves the grader instrument FP=FN=0 on a synthetic
fixture; (2) pins the committed results.json (schema, N>=3, freshness, verdict).
Refreshing results.json is a MANUAL keyed run of run_live.py; CI makes no live calls.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parent.parent
HARNESS = SKILL / "harness"
FIXTURE = HARNESS / "fixture.json"
RESULTS = HARNESS / "results.json"

# Unique module name to avoid sys.modules collision under `pytest skills/`.
_spec = importlib.util.spec_from_file_location("gather_intel_grade", HARNESS / "grade.py")
assert _spec and _spec.loader
grade = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grade)

# Honest MEASURED verdict, pinned (set from results.json after the full N>=3 run).
EXPECTED_VERDICT = "trim"


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
        "results.json missing — run `python3 skills/gather-intel/harness/run_live.py` (keyed).")
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


def test_finding_directional_netpositive_within_noise(results):
    """The MEASURED gather-intel finding: unlike gather-claude (a real fix-worthy
    regression), here the framework is directionally NET-POSITIVE overall
    (verdict_accuracy with_skill >= baseline) and its true_recall dip is WITHIN
    the N=3 noise floor (so the verdict is trim, not fix). Pin both facts."""
    m = results["metrics"]
    wa = m["with_skill"]["verdict_accuracy"]["mean"]
    ba = m["baseline"]["verdict_accuracy"]["mean"]
    assert wa >= ba, f"framework verdict_accuracy {wa} should be >= baseline {ba} (net non-worse)"
    # true_recall dip must be WITHIN noise (this is why it is trim, not a fix-worthy regression)
    tr_dip = m["baseline"]["true_recall"]["mean"] - m["with_skill"]["true_recall"]["mean"]
    tr_noise = m["with_skill"]["true_recall"]["stdev"]
    assert tr_dip <= max(0.05, tr_noise) + 1e-9, (
        f"true_recall dip {tr_dip} exceeds noise floor {max(0.05, tr_noise)}; if it became a "
        "real regression, the verdict should be fix — update EXPECTED_VERDICT + SKILL.md")


def test_results_reproducible_from_committed_sample(results):
    """Verify committed results are reproducible from the sample-records file.

    The sample file is a hand-curated artifact in the format:
    {"runs": [{"records": [{"arm": ..., ...}, ...], "run_idx": N}, ...]}

    To regenerate after refreshing results.json via run_live.py, convert the
    transcripts output to this format: extract records from each transcript,
    group by run, and wrap in {"runs": [...]}. See harness/README.md for details.
    """
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


# ---------- 3. run_live.py error paths (key-free; no live API calls are made) ----------

def _harness_copy(tmp_path):
    """Copy the harness so run_live.py's __file__-relative paths hit the copy."""
    dst = tmp_path / "harness"
    shutil.copytree(HARNESS, dst)
    return dst


def test_run_live_malformed_fixture_clean_error(tmp_path):
    h = _harness_copy(tmp_path)
    (h / "fixture.json").write_text("{bad", encoding="utf-8")
    p = subprocess.run([sys.executable, str(h / "run_live.py"),
                        "--historical-reproduction", "--output", str(h / "runs" / "malformed.json"),
                        "--runs", "1", "--limit", "1"],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 2
    assert "error:" in p.stderr
    assert "Traceback" not in p.stderr


def test_run_live_all_call_errors_exits_nonzero_and_keeps_results(tmp_path):
    h = _harness_copy(tmp_path)
    before = (h / "results.json").read_bytes()
    env = dict(os.environ)
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(k, None)  # keyless: every task CALL_ERRORs at client construction (no network)
    p = subprocess.run([sys.executable, str(h / "run_live.py"),
                        "--historical-reproduction", "--output", str(h / "runs" / "keyless.json"),
                        "--runs", "1"],
                       capture_output=True, text=True, env=env, timeout=120)
    assert p.returncode == 2
    assert "error:" in p.stderr
    assert "Traceback" not in p.stderr
    assert (h / "results.json").read_bytes() == before, (
        "an all-CALL_ERROR run must not overwrite the committed results.json")
