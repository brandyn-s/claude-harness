"""Unit tests for _shared/stats.py — paired-bootstrap CI + CI-aware verdict.

KEY-FREE + deterministic (stats.py is stdlib-only). Covers:
  - separated distributions => CI excludes 0; overlapping => does not
  - determinism for a fixed seed
  - attach_ci / ci_verdict KEEP / TRIM / BLOCKED rule
Run: python3 -m pytest skills/_shared/test_stats.py -q
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

# Load the sibling module by file path (avoids needing skills/ on sys.path).
_HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("shared_stats", _HERE / "stats.py")
assert _spec and _spec.loader
stats = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stats)


# ---------- paired_bootstrap_ci: separation vs overlap ----------

def test_clearly_separated_excludes_zero_positive():
    # with-arm consistently above baseline by ~0.2 each run.
    w = [0.9, 0.92, 0.88, 0.91, 0.89]
    b = [0.7, 0.68, 0.72, 0.69, 0.71]
    r = stats.paired_bootstrap_ci(w, b, seed=0)
    assert r["excludes_zero"] is True
    assert r["direction"] == "positive"
    assert r["ci_low"] > 0.0


def test_clearly_separated_excludes_zero_negative():
    # with-arm consistently BELOW baseline -> CI entirely negative.
    w = [0.5, 0.52, 0.48, 0.51, 0.49]
    b = [0.8, 0.82, 0.78, 0.81, 0.79]
    r = stats.paired_bootstrap_ci(w, b, seed=0)
    assert r["excludes_zero"] is True
    assert r["direction"] == "negative"
    assert r["ci_high"] < 0.0


def test_overlapping_does_not_exclude_zero():
    # per-run deltas straddle 0 (sometimes up, sometimes down) -> inconclusive.
    w = [0.80, 0.60, 0.90, 0.55, 0.85]
    b = [0.70, 0.75, 0.65, 0.80, 0.60]
    r = stats.paired_bootstrap_ci(w, b, seed=0)
    assert r["excludes_zero"] is False
    assert r["direction"] == "inconclusive"
    assert r["ci_low"] < 0.0 < r["ci_high"]


# ---------- determinism ----------

def test_deterministic_for_fixed_seed():
    w = [0.81, 0.62, 0.93, 0.54, 0.88]
    b = [0.70, 0.71, 0.66, 0.79, 0.61]
    r1 = stats.paired_bootstrap_ci(w, b, seed=7)
    r2 = stats.paired_bootstrap_ci(w, b, seed=7)
    assert r1 == r2


def test_different_seeds_can_differ_but_stay_close():
    w = [0.81, 0.62, 0.93, 0.54, 0.88]
    b = [0.70, 0.71, 0.66, 0.79, 0.61]
    r0 = stats.paired_bootstrap_ci(w, b, seed=0)
    r1 = stats.paired_bootstrap_ci(w, b, seed=1)
    # delta_mean is seed-independent (it's the observed mean, not a resample).
    assert r0["delta_mean"] == r1["delta_mean"]


# ---------- input validation ----------

def test_unequal_length_raises():
    with pytest.raises(ValueError):
        stats.paired_bootstrap_ci([0.1, 0.2], [0.1])


def test_empty_raises():
    with pytest.raises(ValueError):
        stats.paired_bootstrap_ci([], [])


# ---------- attach_ci + ci_verdict ----------

def _agg(metric, values):
    """Minimal aggregate dict shaped like aggregate_runs output."""
    return {metric: {"mean": sum(values) / len(values), "values": values}}


def test_attach_ci_writes_ci95_when_paired_values_present():
    w = _agg("accuracy", [0.9, 0.92, 0.88, 0.91])
    b = _agg("accuracy", [0.7, 0.68, 0.72, 0.69])
    stats.attach_ci(w, b, ["accuracy"])
    assert "ci95" in w["accuracy"]
    assert w["accuracy"]["ci95"]["excludes_zero"] is True
    assert w["accuracy"]["ci95"]["direction"] == "positive"


def test_attach_ci_noop_without_values():
    # legacy aggregate (no "values" list) must be left untouched.
    w = {"accuracy": {"mean": 0.9}}
    b = {"accuracy": {"mean": 0.7}}
    stats.attach_ci(w, b, ["accuracy"])
    assert "ci95" not in w["accuracy"]


def test_ci_verdict_keep_on_favorable_exclusion():
    w = _agg("accuracy", [0.9, 0.92, 0.88, 0.91])
    b = _agg("accuracy", [0.7, 0.68, 0.72, 0.69])
    stats.attach_ci(w, b, ["accuracy"])
    v = stats.ci_verdict(w, "accuracy", favorable="higher")
    assert v is not None and v["verdict"] == "keep"


def test_ci_verdict_trim_on_unfavorable_exclusion():
    w = _agg("accuracy", [0.5, 0.52, 0.48, 0.51])
    b = _agg("accuracy", [0.8, 0.82, 0.78, 0.81])
    stats.attach_ci(w, b, ["accuracy"])
    v = stats.ci_verdict(w, "accuracy", favorable="higher")
    assert v is not None and v["verdict"] == "trim"


def test_ci_verdict_blocked_on_overlap():
    w = _agg("accuracy", [0.80, 0.60, 0.90, 0.55, 0.85])
    b = _agg("accuracy", [0.70, 0.75, 0.65, 0.80, 0.60])
    stats.attach_ci(w, b, ["accuracy"])
    v = stats.ci_verdict(w, "accuracy", favorable="higher")
    assert v is not None and v["verdict"] == "BLOCKED ON MEASUREMENT"


def test_ci_verdict_none_without_ci95():
    # No paired CI attached -> caller must fall back to legacy logic.
    w = {"accuracy": {"mean": 0.9}}
    assert stats.ci_verdict(w, "accuracy", favorable="higher") is None
