"""Cohen's kappa — chance-corrected agreement.

Used two ways in the oracle:
  1. Oracle-vs-truth: kappa between Layer A's verdict and the adjudicated
     ground-truth label over the calibration set — a chance-corrected
     companion to the TPR/TNR floors (raw accuracy overstates agreement
     when one class dominates). This gate runs on existing data today.
  2. Inter-rater: kappa between two independent human labelers' labels on
     the same items (``label_a`` / ``label_b`` in Finding.extra, and a
     parallel ``expected-findings-b.yaml`` for Layer C). The helper is
     ready; populating a genuine second-labeler column is a human task —
     this module does NOT fabricate one.

Discipline mirrors ``knowledge-base/harness/ORACLE-PLAN.md`` (kappa >= 0.7
to trust an LLM-judge / labeling process; 0.5-0.7 is a soft warning).
Pure stdlib — no numpy.
"""
from __future__ import annotations

import random


def cohens_kappa(labels_a: list, labels_b: list) -> float:
    """Cohen's kappa for two equal-length label sequences (any hashable
    category values). Returns 1.0 when observed and expected agreement
    are both total (kappa is otherwise undefined at Pe == 1)."""
    n = len(labels_a)
    if n == 0 or len(labels_b) != n:
        raise ValueError("label lists must be equal length and non-empty")
    po = sum(1 for a, b in zip(labels_a, labels_b) if a == b) / n
    cats = set(labels_a) | set(labels_b)
    pe = 0.0
    for c in cats:
        pa = sum(1 for a in labels_a if a == c) / n
        pb = sum(1 for b in labels_b if b == c) / n
        pe += pa * pb
    if pe >= 1.0:
        # Both raters used a single category for every item; agreement is
        # total by construction. kappa is undefined (0/0); report 1.0.
        return 1.0
    return (po - pe) / (1.0 - pe)


def kappa_with_ci(labels_a: list, labels_b: list,
                  n_boot: int = 1000, seed: int = 0) -> tuple[float, tuple[float, float]]:
    """Return (kappa, (ci_lo, ci_hi)) with a bootstrap 95% CI. Seeded for
    reproducibility (the oracle's reproducibility commitment)."""
    k = cohens_kappa(labels_a, labels_b)
    n = len(labels_a)
    pairs = list(zip(labels_a, labels_b))
    rng = random.Random(seed)
    boots: list[float] = []
    for _ in range(n_boot):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        a = [p[0] for p in sample]
        b = [p[1] for p in sample]
        try:
            boots.append(cohens_kappa(a, b))
        except ValueError:
            continue
    if not boots:
        return k, (k, k)
    boots.sort()
    lo = boots[int(0.025 * len(boots))]
    hi = boots[min(len(boots) - 1, int(0.975 * len(boots)))]
    return k, (lo, hi)


def interpret(kappa: float) -> str:
    """Landis & Koch bands, with the oracle's 0.7 trust floor called out."""
    if kappa < 0.0:
        return "worse-than-chance"
    if kappa < 0.20:
        return "slight"
    if kappa < 0.40:
        return "fair"
    if kappa < 0.60:
        return "moderate (below 0.7 trust floor)"
    if kappa < 0.70:
        return "substantial (soft warning: below 0.7 trust floor)"
    if kappa < 0.80:
        return "substantial (>= 0.7 trust floor)"
    return "almost-perfect"
