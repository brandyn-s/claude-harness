"""Cohen's kappa instrument tests — prove the instrument before using it
to gate (verify-effectiveness discipline)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


def _kappa():
    sys.path.insert(0, str(REPO / "skills" / "_shared"))
    sys.modules.pop("oracle.kappa", None)
    from oracle import kappa as k  # noqa: E402
    return k


def test_perfect_agreement_is_one():
    k = _kappa()
    assert k.cohens_kappa([1, 1, 0, 0], [1, 1, 0, 0]) == 1.0


def test_perfect_disagreement_is_negative_one():
    k = _kappa()
    assert k.cohens_kappa([1, 0, 1, 0], [0, 1, 0, 1]) == -1.0


def test_partial_agreement():
    k = _kappa()
    assert abs(k.cohens_kappa([1, 1, 1, 0], [1, 1, 0, 0]) - 0.5) < 1e-9


def test_single_category_total_agreement_returns_one():
    k = _kappa()
    # Pe == 1 (both raters used one category); kappa undefined -> 1.0.
    assert k.cohens_kappa([1, 1, 1], [1, 1, 1]) == 1.0


def test_ci_brackets_point_estimate():
    k = _kappa()
    val, (lo, hi) = k.kappa_with_ci([1, 1, 0, 0, 1, 0], [1, 1, 0, 0, 1, 0], n_boot=200)
    assert lo <= val <= hi


def test_validation_errors():
    k = _kappa()
    with pytest.raises(ValueError):
        k.cohens_kappa([], [])
    with pytest.raises(ValueError):
        k.cohens_kappa([1], [1, 0])


def test_interpret_marks_trust_floor():
    k = _kappa()
    assert "0.7" in k.interpret(0.55)          # below floor -> flagged
    assert k.interpret(0.90) == "almost-perfect"
    assert k.interpret(-0.2) == "worse-than-chance"
