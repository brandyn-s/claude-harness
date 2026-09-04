"""CI gate for the triage live-arm efficacy harness (harness/PROBLEM.md).

KEY-FREE + deterministic. (1) Proves the Spearman + correlation-group grader FP=FN=0
on synthetic inputs with hand-computed values; (2) pins the committed results.json.
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

_spec = importlib.util.spec_from_file_location("triage_grade", HARNESS / "grade.py")
assert _spec and _spec.loader
grade = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grade)

EXPECTED_VERDICT = "trim"

_FX = {"findings": [{"id": f"f{i}", "expert_rank": i, "root_cause": "x"} for i in range(1, 6)],
       "true_groups": [["f1", "f2"], ["f3", "f4"]]}


def test_spearman_grader():
    # perfect ranking -> 1.0
    assert grade.spearman(["f1", "f2", "f3", "f4", "f5"], _FX) == pytest.approx(1.0)
    # fully reversed -> -1.0
    assert grade.spearman(["f5", "f4", "f3", "f2", "f1"], _FX) == pytest.approx(-1.0)
    # omitted ids get worst-rank (still high corr if the order is otherwise right)
    assert grade.spearman(["f1", "f2", "f3"], _FX) > 0.5


def test_group_prf():
    # exact match -> 1/1/1
    assert grade.group_prf([["f1", "f2"], ["f3", "f4"]], _FX["true_groups"]) == (1.0, 1.0, 1.0)
    # over-grouping (f1,f2,f5 adds false pairs) -> precision < 1, recall 1 on that group
    p, r, f1 = grade.group_prf([["f1", "f2", "f5"], ["f3", "f4"]], _FX["true_groups"])
    assert r == pytest.approx(1.0) and p < 1.0
    # missing a group -> recall < 1
    p2, r2, _ = grade.group_prf([["f1", "f2"]], _FX["true_groups"])
    assert r2 == pytest.approx(0.5)


def test_score_run_fp_fn_zero():
    m = grade.score_run(_FX, {"ranking": ["f1", "f2", "f3", "f4", "f5"],
                              "groups": [["f1", "f2"], ["f3", "f4"]]})
    assert m["spearman"] == pytest.approx(1.0)
    assert m["group_f1"] == pytest.approx(1.0)
    assert m["n_ranked"] == 5


# ---------- pin the committed baseline ----------

@pytest.fixture(scope="module")
def results():
    assert RESULTS.exists(), "results.json missing — run run_live.py (keyed)."
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def test_results_protocol_met(results):
    assert results["n_runs"] >= 3
    assert results["n_findings"] == 12
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


def test_finding_both_arms_strong_no_framework_lift(results):
    """Pinned finding: both arms rank near-expert (high Spearman) and the framework's
    ranking gain is within noise (trim). Both detect correlations identically."""
    m = results["metrics"]
    assert m["with_skill"]["spearman"]["mean"] >= 0.85, "framework should still rank well"
    assert m["baseline"]["spearman"]["mean"] >= 0.85, "baseline also ranks well (no framework needed)"
    sp_delta = m["with_skill"]["spearman"]["mean"] - m["baseline"]["spearman"]["mean"]
    sp_noise = max(0.05, m["with_skill"]["spearman"]["stdev"])
    assert sp_delta <= sp_noise + 1e-9, "framework Spearman lift should be within noise (trim)"


def test_results_reproducible_from_committed_sample(results):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sample = json.loads((HARNESS / "runs" / "sample-records-2026-05-31.json").read_text(encoding="utf-8"))
    for arm in ("with_skill", "baseline"):
        agg = grade.aggregate_runs([
            grade.score_run(fixture, next(r for r in run["records"] if r["arm"] == arm))
            for run in sample["runs"]])
        for k in ("spearman", "group_f1"):
            assert abs(agg[k]["mean"] - results["metrics"][arm][k]["mean"]) < 1e-9, (
                f"{arm}.{k}: re-graded sample != committed results")


# ---------- error path: keyless total failure must not clobber the baseline ----------

def test_run_live_keyless_total_failure_exits_2_and_preserves_baseline(tmp_path):
    """run_live.py with no key/SDK auth fails every arm call; it must exit 2 with a
    clean error (no traceback) and leave results.json untouched. Key-free: the
    anthropic client raises before any network attempt."""
    import os
    import shutil
    import subprocess
    import sys

    work = tmp_path / "harness"
    shutil.copytree(HARNESS, work)
    baseline = (work / "results.json").read_bytes()
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")}
    proc = subprocess.run([sys.executable, str(work / "run_live.py"),
                           "--historical-reproduction", "--output", str(work / "runs" / "keyless.json"),
                           "--runs", "1", "--acknowledge-retired-fixture"],
                          capture_output=True, env=env, timeout=120)
    stderr = proc.stderr.decode("utf-8", errors="replace")
    assert proc.returncode == 2, f"expected exit 2, got {proc.returncode}; stderr: {stderr}"
    assert "error:" in stderr and "Traceback" not in stderr
    assert "pass --acknowledge-retired-fixture" not in stderr, "the acknowledged run must get past the fixture gate"
    assert (work / "results.json").read_bytes() == baseline, "committed baseline was overwritten"


# ---------- retired fixture (2026-09-04): a real run needs an explicit acknowledgement ----------

def _keyless_run(tmp_path, *args: str):
    import os
    import shutil
    import subprocess
    import sys

    work = tmp_path / "harness"
    shutil.copytree(HARNESS, work)
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")}
    proc = subprocess.run([sys.executable, str(work / "run_live.py"), *args],
                          capture_output=True, text=True, env=env, timeout=120)
    return work, proc


def test_run_live_refuses_retired_fixture_without_acknowledgement(tmp_path):
    """docs/research-skills-root-cause.md section 7: N=3 of a 12-item ranking cannot resolve the
    arm delta. A real run prints the notice, refuses, and writes nothing."""
    work, proc = _keyless_run(tmp_path, "--historical-reproduction",
                              "--output", str(tmp_path / "harness" / "runs" / "refused.json"), "--runs", "1")
    assert proc.returncode == 2, proc.stderr
    assert "RETIRED (2026-09-04)" in proc.stderr
    assert "--acknowledge-retired-fixture" in proc.stderr and "Traceback" not in proc.stderr
    assert not (work / "runs" / "refused.json").exists()
    assert (work / "results.json").read_bytes() == (HARNESS / "results.json").read_bytes()


def test_plan_only_reports_fixture_status_without_acknowledgement(tmp_path):
    _, proc = _keyless_run(tmp_path, "--historical-reproduction",
                           "--output", str(tmp_path / "plan.json"), "--plan-only")
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
