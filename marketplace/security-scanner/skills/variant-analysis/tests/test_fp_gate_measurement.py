"""CI gate for variant-analysis's FP-cap delivery (and baseline-gate control).

Asserts the *documented contract* of verify_variants.check_fp_gate /
check_baseline directly — independent of harness/measure.py's own verdicts.

Contract under test (hand-derived from SKILL.md "50%+ FP rate means you've gone
too generic", METHODOLOGY.md audit-triage <50%, harness-pattern.md "skipped
checks ... don't masquerade as passes"):

  FP gate
    * FP rate > cap                      -> FAIL (block over-generalized pattern)
    * FP rate <= cap (sampled)           -> PASS
    * non-empty match set, NO sample     -> must NOT emit a bare PASS (UNVERIFIED)
    * zero matches, no sample            -> PASS (vacuously within cap)
  Baseline gate
    * seed_file:seed_line present        -> PASS
    * wrong line / wrong file / no match -> FAIL

WAVE-1 STATE (before the proposed fix): the no-sample case returns a bare
passed=True ("gate informational only") -> the cap is INERT by default. The two
xfail-marked tests below pin that deficiency and FLIP TO PASS once the fix lands
(missing sample on a non-empty match set => non-PASS). Remove the xfail markers
when applying the fix.
"""
import io
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
HARNESS = Path(__file__).resolve().parents[1] / "harness"
sys.path.insert(0, str(SCRIPTS))

from verify_variants import check_fp_gate, check_baseline  # noqa: E402


def _emitted(buf):
    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    return json.loads(lines[-1]) if lines else {}


# --------------------------------------------------------------------------
# FP gate — the parts that work today (cap enforced WHEN a sample is present)
# --------------------------------------------------------------------------

def test_fp_gate_fails_over_cap():
    """A pattern whose sampled FP rate exceeds the cap MUST fail the gate."""
    buf = io.StringIO()
    passed = check_fp_gate(n_matches=200, fp_rate_cap=0.5, sampled_fp=150, ndjson=buf)
    assert passed is False, "75% FP rate must fail the documented 50% cap"
    rec = _emitted(buf)
    assert rec["fp_rate"] > rec["cap"]


def test_fp_gate_passes_under_cap():
    buf = io.StringIO()
    passed = check_fp_gate(n_matches=100, fp_rate_cap=0.5, sampled_fp=10, ndjson=buf)
    assert passed is True, "10% FP rate is within the 50% cap"


def test_fp_gate_passes_at_boundary():
    buf = io.StringIO()
    passed = check_fp_gate(n_matches=100, fp_rate_cap=0.5, sampled_fp=50, ndjson=buf)
    assert passed is True, "exactly 50% (== cap) is acceptable; 'exceeds' is strict"


def test_fp_gate_passes_when_no_matches():
    """Zero matches => no FPs possible => legitimate pass (guards over-correction)."""
    buf = io.StringIO()
    passed = check_fp_gate(n_matches=0, fp_rate_cap=0.5, sampled_fp=None, ndjson=buf)
    assert passed is True


# --------------------------------------------------------------------------
# FP gate — the Wave-1 deficiency: inert by default (no sample => bare PASS).
# These pin the bug now and FLIP TO PASS after the proposed fix. Drop xfail then.
# --------------------------------------------------------------------------

def test_fp_gate_does_not_emit_bare_pass_without_sample():
    """A non-empty match set with NO FP sample must NOT silently PASS.

    The gate has zero evidence the FP rate is under cap, so per the documented
    contract it must return a non-PASS (UNVERIFIED) verdict rather than a bare
    passed=True. This is variant-analysis's only quality bound; a default-path
    rubber stamp makes it inert.
    """
    buf = io.StringIO()
    passed = check_fp_gate(n_matches=5000, fp_rate_cap=0.5, sampled_fp=None, ndjson=buf)
    assert passed is not True, (
        "5000 matches with no FP sample must not pass --strict; "
        "cap is UNVERIFIED, not satisfied"
    )


def test_harness_reports_no_contract_violations():
    """End-to-end: measure.py exits 0 only when the gate honors the contract."""
    r = subprocess.run(
        [sys.executable, str(HARNESS / "measure.py"), "--json"],
        capture_output=True, text=True, timeout=60,
    )
    m = json.loads(r.stdout)
    assert m["inert_fp_gate"] is False, "FP cap must not be inert by default"
    assert m["n_contract_violations"] == 0, m["contract_violations"]
    assert r.returncode == 0


# --------------------------------------------------------------------------
# Baseline gate — the control: Wave 1 said this half is sound. Confirm it.
# --------------------------------------------------------------------------

def test_baseline_passes_on_seed_hit():
    buf = io.StringIO()
    matches = [{"file": "src/api/users.py", "line": "42", "snippet": "x"}]
    assert check_baseline("api/users.py", 42, matches, buf) is True


def test_baseline_fails_on_wrong_seed_line():
    """Right file, wrong line => seed bug not matched => baseline FAIL (sound)."""
    buf = io.StringIO()
    matches = [{"file": "src/api/users.py", "line": "99", "snippet": "x"}]
    assert check_baseline("api/users.py", 42, matches, buf) is False


def test_baseline_fails_on_wrong_seed_file():
    buf = io.StringIO()
    matches = [{"file": "src/api/orders.py", "line": "42", "snippet": "x"}]
    assert check_baseline("api/users.py", 42, matches, buf) is False


def test_baseline_fails_on_no_matches():
    buf = io.StringIO()
    assert check_baseline("api/users.py", 42, [], buf) is False
