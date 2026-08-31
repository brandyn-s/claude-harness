"""CI gate for the roundtable consensus-integrity harness (harness/PROBLEM.md).

Pins the frozen baseline: the convergence auto-stop must NEVER declare consensus
on a sub-quorum collapse (false_consensus_count == 0), and the quorum guard must
not suppress real consensus (consensus_recall == 100%). Regression here means
roundtable's decorrelated-multi-vendor value-prop is no longer delivered.
"""
from __future__ import annotations

import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent / "harness"

# Path-load this skill's harness measure.py under a UNIQUE module name. Several
# skills ship a harness/measure.py; a bare `from measure import ...` collides in
# sys.modules under `pytest skills/` (first import wins), binding the gate to the
# wrong skill's measurement.
import importlib.util  # noqa: E402
_spec = importlib.util.spec_from_file_location("roundtable_consensus_measure", HARNESS / "measure.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
run_measurement = _mod.run_measurement


def test_no_false_consensus():
    m = run_measurement()
    bad = [r["id"] for r in m["rows"] if r["false_consensus"]]
    assert m["false_consensus_count"] == 0, (
        f"auto-stop declared consensus on sub-quorum collapse scenarios {bad} — "
        f"roundtable's decorrelation value-prop is not delivered (see harness/PROBLEM.md)"
    )


def test_quorum_guard_does_not_suppress_real_consensus():
    m = run_measurement()
    assert m["consensus_recall"] == 1.0, (
        f"consensus_recall={m['consensus_recall']:.0%}: the quorum guard wrongly "
        f"suppressed a genuine >=2-vendor consensus (over-correction)"
    )


def test_full_integrity():
    m = run_measurement()
    misses = [r["id"] for r in m["rows"] if not r["correct"]]
    assert m["integrity"] == 1.0, f"should_stop disagreed with the oracle on {misses}"
