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

_FIXTURE = json.loads(FIXTURE.read_text(encoding="utf-8"))


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


# ---------- 1b. 2026-09-03 oracle revision (docs/research-skills-root-cause.md section 5) ----------

def test_ungroundable_claim_is_excluded_from_grounding_precision_but_still_scored():
    fixture = {"claims": [
        {"id": "A", "category": "true_primary", "expected_disposition": "supported",
         "grounding_terms": ["alpha"]},
        {"id": "H", "category": "true_primary", "expected_disposition": "supported",
         "grounding_terms": ["verbatim phrase from one repo"], "groundable": False},
        {"id": "F", "category": "fabricated", "expected_disposition": "not_supported",
         "grounding_terms": ["fake"]},
    ]}
    recs = [{"id": "A", "raw_verdict": "SUPPORTED", "cited_urls": ["u"], "grounded": True},
            # a SUPPORTED on the un-groundable heuristic: previously an ungrounded assertion
            {"id": "H", "raw_verdict": "SUPPORTED", "cited_urls": ["u"], "grounded": False},
            {"id": "F", "raw_verdict": "UNCHARTED", "cited_urls": [], "grounded": None}]
    m = grade.score_run(fixture, recs)
    assert m["grounding_precision"] == pytest.approx(1.0), "H is un-groundable: excluded from the denominator"
    assert (m["n_supported"], m["n_supported_groundable"], m["n_grounded_supported"]) == (2, 1, 1)
    assert m["true_recall"] == pytest.approx(1.0) and m["verdict_accuracy"] == pytest.approx(1.0), (
        "H still counts on disposition")
    row = next(r for r in m["rows"] if r["id"] == "H")
    assert row["groundable"] is False and row["grounded"] is None
    # a CONTESTED on the un-groundable claim is still a wrong disposition (true_recall drops)
    recs2 = [recs[0], {"id": "H", "raw_verdict": "CONTESTED", "cited_urls": [], "grounded": None}, recs[2]]
    m2 = grade.score_run(fixture, recs2)
    assert m2["true_recall"] == pytest.approx(0.5) and m2["grounding_precision"] == pytest.approx(1.0)


def test_three_workers_sweetspot_is_marked_ungroundable_with_lineage():
    claim = next(c for c in _FIXTURE["claims"] if c["id"] == "three-workers-sweetspot")
    assert claim["groundable"] is False
    assert "0/11" in claim["grounding_note"], "the note records the evidence: never grounded in either run"
    others = [c for c in _FIXTURE["claims"] if c["id"] != "three-workers-sweetspot"]
    assert all(c.get("groundable", True) for c in others), "only the one fuzzy heuristic claim is un-groundable"
    revisions = _FIXTURE["_revisions"]
    assert revisions[0]["supersedes_sha"] == "6a017f97d139", "the frozen results.json was measured against 6a017f97d139"
    assert revisions[0]["frozen_sample_regrade"] == {"grounding_precision": {"with_skill": 1.0, "baseline": 1.0}}


def _fixture_lineage() -> set[str]:
    """Current fixture sha plus every sha it is a documented revision of (`_revisions`)."""
    return {sha256(FIXTURE.read_bytes()).hexdigest()[:12]} | {
        r["supersedes_sha"] for r in _FIXTURE.get("_revisions", [])}


def _expected_frozen_value(results: dict, arm: str, metric: str):
    """What the committed 2026-05-31 sample must re-grade to under the CURRENT fixture:
    the frozen results.json value, unless a documented `_revisions` entry records that
    the oracle correction changes how the frozen sample grades on that metric."""
    for rev in _FIXTURE.get("_revisions", []):
        override = rev.get("frozen_sample_regrade", {}).get(metric, {})
        if arm in override:
            return override[arm]
    return results["metrics"][arm][metric]["mean"]


def _run_regrade(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(HARNESS / "regrade.py"), *args],
                          capture_output=True, text=True, timeout=120, check=False)


def test_regrade_tool_reproduces_frozen_baseline_under_documented_revision(results, tmp_path):
    """regrade.py (no API calls, no fetches) re-derives the frozen 2026-05-31 numbers from
    the committed sample on every metric except the one the documented revision changes
    (grounding_precision 0.878/0.833 -> 1.0/1.0: every sub-1.0 value was the un-groundable claim)."""
    out = tmp_path / "regrade-frozen.json"
    proc = _run_regrade("--records", str(HARNESS / "runs" / "sample-records-2026-05-31.json"),
                        "--run-date", results["run_date"], "--model", results["model"], "--output", str(out))
    assert proc.returncode == 0, proc.stderr
    rg = json.loads(out.read_text(encoding="utf-8"))
    for arm in ("with_skill", "baseline"):
        for k in grade._METRIC_KEYS:
            assert abs(rg["metrics"][arm][k]["mean"] - _expected_frozen_value(results, arm, k)) < 1e-9, f"{arm}.{k}"
    assert rg["metrics"]["with_skill"]["grounding_precision"]["mean"] == pytest.approx(1.0)
    assert rg["metrics"]["baseline"]["grounding_precision"]["mean"] == pytest.approx(1.0)
    # with a zero grounding_precision delta the CI-aware rule (added after the freeze) says BLOCKED
    assert rg["verdict"]["verdict"] == "BLOCKED ON MEASUREMENT"


def test_regrade_refuses_to_overwrite_frozen_results(tmp_path):
    proc = _run_regrade("--records", str(HARNESS / "runs" / "sample-records-2026-05-31.json"),
                        "--run-date", "2026-05-31", "--model", "claude-opus-4-8", "--output", str(RESULTS))
    assert proc.returncode == 2
    assert "immutable" in proc.stderr


REGRADE_2026_09_03 = HARNESS / "runs" / "regrade-2026-09-03.json"
SAMPLE_2026_09_03 = HARNESS / "runs" / "sample-records-2026-09-03.json"


def test_regrade_2026_09_03_is_reproducible_and_baseline_at_ceiling(tmp_path):
    """The offline re-grade of the 2026-09-03 Fable 5.1 rerun (docs/research-skills-root-cause.md
    section 12) re-derives from its committed compact sample. Under the corrected oracle the
    grounding_precision delta that drove the live verdict is 0.0 and the baseline is at ceiling."""
    committed = json.loads(REGRADE_2026_09_03.read_text(encoding="utf-8"))
    assert committed["model"] == "claude-fable-5-1" and committed["run_date"] == "2026-09-03"
    out = tmp_path / "regrade.json"
    proc = _run_regrade("--records", str(SAMPLE_2026_09_03), "--run-date", committed["run_date"],
                        "--model", committed["model"], "--output", str(out))
    assert proc.returncode == 0, proc.stderr
    rg = json.loads(out.read_text(encoding="utf-8"))
    assert rg["verdict"]["verdict"] == committed["verdict"]["verdict"]
    for arm in ("with_skill", "baseline"):
        for k in grade._METRIC_KEYS:
            assert abs(rg["metrics"][arm][k]["mean"] - committed["metrics"][arm][k]["mean"]) < 1e-9, f"{arm}.{k}"
    m = committed["metrics"]
    assert m["with_skill"]["grounding_precision"]["mean"] == pytest.approx(1.0)
    assert m["baseline"]["grounding_precision"]["mean"] == pytest.approx(1.0)
    assert committed["verdict"]["delta"] == pytest.approx(0.0)
    assert m["baseline"]["verdict_accuracy"]["mean"] == pytest.approx(1.0), (
        "the baseline is at ceiling on this fixture: the harness cannot separate the arms")
    assert committed["regrade"]["fixture_sha"] == sha256(FIXTURE.read_bytes()).hexdigest()[:12]


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
    """The frozen results were measured against fixture 6a017f97d139. An oracle correction
    may revise fixture.json WITHOUT a live re-run (results.json is immutable) only if it
    records the superseded sha in `_revisions` and documents any metric whose frozen-sample
    re-grade it changes (test_results_reproducible_from_committed_sample)."""
    assert results["fixture_sha"] in _fixture_lineage(), (
        "results.json measured against a fixture.json that is not in the current fixture's "
        "revision lineage — re-run run_live.py or record the revision in fixture.json `_revisions`.")


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
            # frozen value, or the value a documented fixture revision says the frozen
            # sample now grades to (2026-09-03: grounding_precision 1.0/1.0)
            assert abs(agg[k]["mean"] - _expected_frozen_value(results, arm, k)) < 1e-9, (
                f"{arm}.{k}: re-graded sample != committed results (or documented revision)")


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
                        "--runs", "1", "--limit", "1", "--acknowledge-retired-fixture"],
                       capture_output=True, text=True, timeout=120)
    assert p.returncode == 2
    assert "error:" in p.stderr
    assert "Traceback" not in p.stderr
    assert "pass --acknowledge-retired-fixture" not in p.stderr, "the acknowledged run must get past the fixture gate"


def test_run_live_all_call_errors_exits_nonzero_and_keeps_results(tmp_path):
    h = _harness_copy(tmp_path)
    before = (h / "results.json").read_bytes()
    env = dict(os.environ)
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(k, None)  # keyless: every task CALL_ERRORs at client construction (no network)
    p = subprocess.run([sys.executable, str(h / "run_live.py"),
                        "--historical-reproduction", "--output", str(h / "runs" / "keyless.json"),
                        "--runs", "1", "--acknowledge-retired-fixture"],
                       capture_output=True, text=True, env=env, timeout=120)
    assert p.returncode == 2
    assert "error:" in p.stderr
    assert "Traceback" not in p.stderr
    assert "pass --acknowledge-retired-fixture" not in p.stderr, "the acknowledged run must get past the fixture gate"
    assert (h / "results.json").read_bytes() == before, (
        "an all-CALL_ERROR run must not overwrite the committed results.json")


# ---------- 4. Retired fixture (2026-09-04): a real run needs an explicit acknowledgement ----------

def test_run_live_refuses_retired_fixture_without_acknowledgement(tmp_path):
    """docs/research-skills-root-cause.md sections 5 and 12.2: the baseline is at ceiling and the
    corrected oracle shows identical arms. A real run prints the notice, refuses, writes nothing."""
    h = _harness_copy(tmp_path)
    before = (h / "results.json").read_bytes()
    env = dict(os.environ)
    for k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        env.pop(k, None)
    p = subprocess.run([sys.executable, str(h / "run_live.py"),
                        "--historical-reproduction", "--output", str(h / "runs" / "refused.json"),
                        "--runs", "1"],
                       capture_output=True, text=True, env=env, timeout=120)
    assert p.returncode == 2, p.stderr
    assert "RETIRED (2026-09-04)" in p.stderr
    assert "--acknowledge-retired-fixture" in p.stderr and "Traceback" not in p.stderr
    assert not (h / "runs" / "refused.json").exists()
    assert (h / "results.json").read_bytes() == before


def test_plan_only_reports_fixture_status_without_acknowledgement(tmp_path):
    p = subprocess.run([sys.executable, str(HARNESS / "run_live.py"),
                        "--historical-reproduction", "--output", str(tmp_path / "plan.json"), "--plan-only"],
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    receipt = json.loads(p.stdout)
    assert receipt["fixture_status"] == "retired"
    assert receipt["fixture_status_since"] == "2026-09-04"
    assert receipt["retired_fixture_acknowledged"] is False
    assert not (tmp_path / "plan.json").exists()


def test_harness_docs_record_the_retirement():
    for name in ("README.md", "PROBLEM.md"):
        text = (HARNESS / name).read_text(encoding="utf-8")
        assert "Retired at this fixture (2026-09-04)" in text, name
        assert "research-skills-root-cause.md" in text and "--acknowledge-retired-fixture" in text, name
