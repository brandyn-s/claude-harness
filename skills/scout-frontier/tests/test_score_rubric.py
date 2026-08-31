"""Golden tests for score_rubric.py (scout-frontier Step 8 instrument).

Verify the scorer enforces the two contracts from SKILL.md Step 8:
  - TPR = 1.0: every expected_paradigm_distinct finding recomputes to distance >= 1
  - FPR = 0:   every negative_control recomputes to distance 0

and the supporting guards:
  - controls without axis values are unverifiable and block a clean pass
  - declared/computed arithmetic drift (FP/FN) fails
  - malformed / incomplete fixtures exit 2

Exit codes: 0 = pass, 1 = mismatch, 2 = malformed input.
"""
import json
import subprocess
import sys
from pathlib import Path

SCORER = Path(__file__).parent.parent / "scripts" / "score_rubric.py"
FIXTURES = Path(__file__).parent.parent / "test-fixtures"

INCUMBENT = {
    "name": "code-graph",
    "data_structure": "graph",
    "computation_model": "traversal",
    "abstraction_level": "symbol",
    "time_dynamics": "static-with-incremental",
}


def run(fixture: dict | str, tmp_path: Path) -> tuple[int, str]:
    f = tmp_path / "fixture.json"
    f.write_text(fixture if isinstance(fixture, str) else json.dumps(fixture), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCORER), str(f)],
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


def base_fixture(**overrides) -> dict:
    fx = {
        "fixture_name": "unit-test",
        "version": "1.0",
        "incumbent": dict(INCUMBENT),
        "expected_paradigm_distinct": [
            {"name": "distinct-1", "data_structure": "fact-database",
             "computation_model": "datalog-inference", "abstraction_level": "symbol",
             "time_dynamics": "static", "distance": 3},
        ],
        "negative_controls": [
            {"name": "control-1", "data_structure": "graph", "computation_model": "traversal",
             "abstraction_level": "symbol", "time_dynamics": "static-with-incremental",
             "distance": 0},
        ],
    }
    fx.update(overrides)
    return fx


# --- shipped fixtures pass --------------------------------------------------

def test_shipped_code_intel_fixture_passes():
    result = subprocess.run(
        [sys.executable, str(SCORER), str(FIXTURES / "code-intel-paradigms.json")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TPR (expected scoring distance >= 1): 1.00" in result.stdout
    assert "FPR (controls scoring distance > 0):  0.00" in result.stdout


def test_shipped_observability_fixture_passes():
    result = subprocess.run(
        [sys.executable, str(SCORER), str(FIXTURES / "observability-paradigms.json")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


# --- TPR contract -----------------------------------------------------------

def test_expected_finding_that_computes_zero_is_tpr_fail(tmp_path):
    """A 'paradigm-distinct' finding whose axes equal the incumbent must fail (TPR < 1)."""
    fx = base_fixture(expected_paradigm_distinct=[
        {"name": "secretly-same-paradigm", "data_structure": "graph",
         "computation_model": "traversal", "abstraction_level": "symbol",
         "time_dynamics": "static-with-incremental", "distance": 0},
    ])
    code, out = run(fx, tmp_path)
    assert code == 1, out
    assert "TPR-FAIL" in out
    assert "TPR < 1.0" in out or "scored distance 0" in out


# --- FPR contract -----------------------------------------------------------

def test_negative_control_that_computes_nonzero_is_fpr_fail(tmp_path):
    """A negative control whose axes differ from the incumbent must fail (FPR > 0)."""
    fx = base_fixture(negative_controls=[
        {"name": "actually-distinct", "data_structure": "vector",
         "computation_model": "learning", "abstraction_level": "symbol",
         "time_dynamics": "static-with-incremental", "distance": 0},
    ])
    code, out = run(fx, tmp_path)
    assert code == 1, out
    assert "FPR-FAIL" in out


def test_control_without_axes_is_unverifiable(tmp_path):
    """A control with no axis values cannot be verified and must block a clean pass."""
    fx = base_fixture(negative_controls=[{"name": "bare-control", "distance": 0}])
    code, out = run(fx, tmp_path)
    assert code == 1, out
    assert "unverifiable" in out.lower() or "no axis values" in out.lower()


# --- arithmetic drift -------------------------------------------------------

def test_declared_less_than_computed_is_fp(tmp_path):
    fx = base_fixture(expected_paradigm_distinct=[
        {"name": "under-declared", "data_structure": "fact-database",
         "computation_model": "datalog-inference", "abstraction_level": "symbol",
         "time_dynamics": "static", "distance": 1},  # really computes 3
    ])
    code, out = run(fx, tmp_path)
    assert code == 1, out
    assert "FP" in out


def test_declared_more_than_computed_is_fn(tmp_path):
    fx = base_fixture(expected_paradigm_distinct=[
        {"name": "over-declared", "data_structure": "graph",
         "computation_model": "learning", "abstraction_level": "symbol",
         "time_dynamics": "static-with-incremental", "distance": 3},  # really computes 1
    ])
    code, out = run(fx, tmp_path)
    assert code == 1, out
    assert "FN" in out


# --- malformed input --------------------------------------------------------

def test_malformed_json_exits_2(tmp_path):
    code, out = run("{not valid json", tmp_path)
    assert code == 2, out


def test_missing_top_level_field_exits_2(tmp_path):
    fx = base_fixture()
    del fx["incumbent"]
    code, out = run(fx, tmp_path)
    assert code == 2, out
    assert "incumbent" in out.lower()


def test_incumbent_missing_axis_exits_2(tmp_path):
    fx = base_fixture()
    del fx["incumbent"]["time_dynamics"]
    code, out = run(fx, tmp_path)
    assert code == 2, out
    assert "time_dynamics" in out


def test_empty_expected_and_controls_exits_2(tmp_path):
    """Degenerate fixture with zero findings and zero controls must not vacuously pass."""
    fx = base_fixture(expected_paradigm_distinct=[], negative_controls=[])
    code, out = run(fx, tmp_path)
    assert code == 2, out
    assert "PASS" not in out
    assert "Traceback" not in out


def test_non_object_entry_exits_2_without_traceback(tmp_path):
    """String entries in expected_paradigm_distinct are malformed input, not a mismatch."""
    fx = base_fixture(expected_paradigm_distinct=["finding-as-string"])
    code, out = run(fx, tmp_path)
    assert code == 2, out
    assert "AttributeError" not in out
    assert "Traceback" not in out


def test_non_list_controls_exits_2_without_traceback(tmp_path):
    """A non-list negative_controls value is malformed input, not iterable chars."""
    fx = base_fixture(negative_controls="not-a-list")
    code, out = run(fx, tmp_path)
    assert code == 2, out
    assert "Traceback" not in out


def test_clean_synthetic_fixture_passes(tmp_path):
    code, out = run(base_fixture(), tmp_path)
    assert code == 0, out
    assert "PASS" in out
