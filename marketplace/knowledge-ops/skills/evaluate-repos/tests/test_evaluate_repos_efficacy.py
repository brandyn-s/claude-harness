"""CI gate for the evaluate-repos live-arm efficacy harness (harness/PROBLEM.md).

KEY-FREE + deterministic. (1) Proves the de-bias grader FP=FN=0 on a synthetic fixture
with hand-computed metrics; (2) pins the committed results.json. Refreshing results.json
is a MANUAL keyed run of run_live.py; CI makes no live calls.
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

_spec = importlib.util.spec_from_file_location("evaluate_repos_grade", HARNESS / "grade.py")
assert _spec and _spec.loader
grade = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grade)

# Honest MEASURED verdict, pinned (set from results.json after the full N>=3 run).
EXPECTED_VERDICT = "fix"


# ---------- 1. Prove the de-bias grader (FP=FN=0) ----------

_SYNTH_FIXTURE = {
    "patterns": [
        {"id": "A", "disposition": "should_adopt", "look_dismissable": True, "pattern": "x"},
        {"id": "B", "disposition": "should_adopt", "look_dismissable": False, "pattern": "x"},
        {"id": "C", "disposition": "should_reject", "look_dismissable": False, "pattern": "x"},
        {"id": "D", "disposition": "should_reject", "look_dismissable": False, "pattern": "x"},
    ]
}
# A: wrongly REJECTED (false dismissal of a dismissable-adopt). B: correctly ADOPTED.
# C: wrongly ADOPTED (over-adoption). D: correctly REJECTED.
_SYNTH_RECORDS = [
    {"id": "A", "decision": "REJECT"},
    {"id": "B", "decision": "we should ADOPT this"},
    {"id": "C", "decision": "ADOPT"},
    {"id": "D", "decision": "REJECT this, not worth it"},
]


def test_debias_grader_fp_fn_zero():
    m = grade.score_run(_SYNTH_FIXTURE, _SYNTH_RECORDS)
    assert m["decision_accuracy"] == pytest.approx(0.5), "B,D correct; A,C wrong"
    assert m["false_dismissal_rate"] == pytest.approx(0.5), "of {A,B} adopt-targets, A dismissed"
    assert m["hard_reject_rate"] == pytest.approx(0.5), "A hard-rejected"
    assert m["dismissable_dismissal_rate"] == pytest.approx(1.0), "the one dismissable adopt (A) dismissed"
    assert m["over_adoption_rate"] == pytest.approx(0.5), "of {C,D} reject-targets, C adopted"


def test_normalize_decision():
    for v in ["ADOPT", "we should adopt", "yes, adopt it", "in favor"]:
        assert grade.normalize_decision(v) == "ADOPT", v
    for v in ["REJECT", "do not adopt", "should not adopt", "decline"]:
        assert grade.normalize_decision(v) == "REJECT", v
    for v in ["DEFER", "wait and monitor", "revisit later", "needs more", "", "garbled"]:
        assert grade.normalize_decision(v) == "DEFER", v


def test_decide_verdict_logic():
    # harness lowers false-dismissal beyond noise, no over-adoption -> keep
    w = {"false_dismissal_rate": {"mean": 0.1, "stdev": 0.0}, "over_adoption_rate": {"mean": 0.1, "stdev": 0.0}}
    b = {"false_dismissal_rate": {"mean": 0.4, "stdev": 0.0}, "over_adoption_rate": {"mean": 0.1, "stdev": 0.0}}
    assert grade.decide_verdict(w, b)["verdict"] == "keep"
    # harness over-adopts -> fix
    w2 = {"false_dismissal_rate": {"mean": 0.0, "stdev": 0.0}, "over_adoption_rate": {"mean": 0.5, "stdev": 0.0}}
    b2 = {"false_dismissal_rate": {"mean": 0.4, "stdev": 0.0}, "over_adoption_rate": {"mean": 0.1, "stdev": 0.0}}
    assert grade.decide_verdict(w2, b2)["verdict"] == "fix"
    # no measurable de-bias -> trim
    w3 = {"false_dismissal_rate": {"mean": 0.35, "stdev": 0.0}, "over_adoption_rate": {"mean": 0.1, "stdev": 0.0}}
    b3 = {"false_dismissal_rate": {"mean": 0.4, "stdev": 0.0}, "over_adoption_rate": {"mean": 0.1, "stdev": 0.0}}
    assert grade.decide_verdict(w3, b3)["verdict"] == "trim"
    # de-bias BACKFIRES (harness dismisses MORE) -> fix  (the measured evaluate-repos case)
    w4 = {"false_dismissal_rate": {"mean": 0.86, "stdev": 0.0}, "over_adoption_rate": {"mean": 0.0, "stdev": 0.0}}
    b4 = {"false_dismissal_rate": {"mean": 0.29, "stdev": 0.0}, "over_adoption_rate": {"mean": 0.0, "stdev": 0.0}}
    assert grade.decide_verdict(w4, b4)["verdict"] == "fix"


# ---------- 2. Pin the committed frozen baseline ----------

@pytest.fixture(scope="module")
def results():
    assert RESULTS.exists(), "results.json missing — run run_live.py (keyed)."
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def test_results_protocol_met(results):
    assert results["n_runs"] >= 3
    assert results["n_patterns"] == 14
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


def test_finding_debias_backfires_on_auto_synthesis(results):
    """The MEASURED finding (post over-dismissal guard, 2026-05-31): with an LLM SYNTHESIS
    standing in for the human decider, the advocate/skeptic harness STILL increases
    false-dismissal vs a decisive single self-eval pass. The over-dismissal guard HALVED the
    backfire (false_dismissal 0.857 -> 0.524, hard-rejects of good patterns -> 0) but did NOT
    rescue it — the guarded synthesizer still over-hedges to DEFER (0.524 > baseline 0.286),
    keeping accuracy below baseline without meaningful over-adoption. (Validity caveat in
    PROBLEM.md §5-6: the real skill keeps the HUMAN as decider, un-measured here; the residual
    backfire empirically grounds that design.) Pin the persisting backfire."""
    m = results["metrics"]
    fdw = m["with_skill"]["false_dismissal_rate"]["mean"]
    fdb = m["baseline"]["false_dismissal_rate"]["mean"]
    assert fdw - fdb > 0.05, f"harness false_dismissal {fdw} should be > baseline {fdb} (backfire)"
    assert m["with_skill"]["decision_accuracy"]["mean"] < m["baseline"]["decision_accuracy"]["mean"], (
        "harness accuracy should be below baseline (the over-hedging cost)")
    assert m["with_skill"]["over_adoption_rate"]["mean"] <= m["baseline"]["over_adoption_rate"]["mean"] + 0.05, (
        "the backfire is over-DISMISSAL, not over-adoption (neither arm over-adopts)")


def test_results_reproducible_from_committed_sample(results):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sample = json.loads((HARNESS / "runs" / "sample-records-2026-05-31.json").read_text(encoding="utf-8"))
    for arm in ("with_skill", "baseline"):
        agg = grade.aggregate_runs([
            grade.score_run(fixture, [r for r in run["records"] if r["arm"] == arm])
            for run in sample["runs"]])
        for k in ("decision_accuracy", "false_dismissal_rate", "over_adoption_rate"):
            a, c = agg[k], results["metrics"][arm][k]
            if a is None or c is None:
                assert a == c, f"{arm}.{k}: presence mismatch"
            else:
                assert abs(a["mean"] - c["mean"]) < 1e-9, f"{arm}.{k}: re-graded sample != committed"


# ---------- 3. run_live.py error paths (key-free — never makes a live call) ----------

def _run_live_copy(tmp_path: Path, fixture_text: str) -> subprocess.CompletedProcess:
    """Run a tmp copy of run_live.py with every ANTHROPIC_* env var stripped."""
    for name in ("run_live.py", "grade.py", "results.json"):
        shutil.copy(HARNESS / name, tmp_path / name)
    (tmp_path / "fixture.json").write_text(fixture_text, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("ANTHROPIC")}
    return subprocess.run([sys.executable, str(tmp_path / "run_live.py"),
                           "--historical-reproduction", "--output", str(tmp_path / "runs" / "test.json"),
                           "--runs", "1",
                           "--workers", "2"], capture_output=True, env=env, timeout=120)


def test_run_live_bad_fixture_clean_error(tmp_path):
    """Malformed fixture.json -> 'error: ...' to stderr + exit 2, no traceback."""
    proc = _run_live_copy(tmp_path, "{bad")
    out = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
    assert proc.returncode == 2, out
    assert "error: fixture.json missing or invalid" in out
    assert "Traceback" not in out


def test_run_live_all_errors_abort_without_results(tmp_path):
    """With no ANTHROPIC_* env every API call fails fast; run_live must exit non-zero
    and refuse to write results.json instead of grading a 100%-failed measurement."""
    before = (HARNESS / "results.json").read_bytes()
    proc = _run_live_copy(tmp_path, FIXTURE.read_text(encoding="utf-8"))
    out = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
    assert proc.returncode == 1, out
    assert "API calls failed" in out
    assert "Traceback" not in out
    assert (tmp_path / "results.json").read_bytes() == before
