#!/usr/bin/env python3
"""Stdlib-only paired-bootstrap confidence intervals for the skill efficacy harnesses.

Ported from the paired-bootstrap CI used in code-search's eval runbook
(`bench/research/paired_bootstrap_*`). The skill graders run a small number N of
*paired* A/B runs: each run produces a with-skill metric value and a baseline
metric value scored on the SAME fixture under the SAME conditions. Because the
two arms share the run's nuisance variation (model sampling, fixture order), the
honest uncertainty estimate resamples the *per-run deltas*, not the two arms
independently.

`paired_bootstrap_ci` resamples the per-run deltas with replacement `n_boot`
times, takes the mean delta of each resample, and reports the percentile CI of
that bootstrap distribution. It is fully deterministic given `seed` (uses a
local `random.Random(seed)` — never touches global RNG state), so a grader's
verdict is reproducible run-to-run for a fixed set of paired values.

This module performs NO network/API calls and imports only the stdlib, so it is
safe to import from any harness `grade.py` and to unit-test in CI without keys.
"""
from __future__ import annotations

import random
from typing import Sequence


def paired_bootstrap_ci(
    with_vals: Sequence[float],
    without_vals: Sequence[float],
    n_boot: int = 10000,
    ci: float = 0.95,
    seed: int = 0,
) -> dict:
    """Paired-bootstrap CI of the mean per-run delta (with_skill - baseline).

    Args:
        with_vals:    per-run metric values for the with-skill arm.
        without_vals: per-run metric values for the baseline arm. MUST be the
                      same length as `with_vals` and paired index-for-index
                      (run i of with_vals corresponds to run i of without_vals).
        n_boot:       number of bootstrap resamples.
        ci:           central CI mass (0.95 -> 2.5th/97.5th percentiles).
        seed:         seed for the local RNG -> deterministic output.

    Returns:
        dict with:
          delta_mean    : mean of the observed per-run deltas.
          ci_low/ci_high: percentile CI bounds of the bootstrap delta means.
          excludes_zero : True iff the whole CI is strictly above or below 0.
          direction     : "positive" (CI entirely > 0), "negative" (entirely
                          < 0), or "inconclusive" (CI straddles 0).
          n             : number of paired runs.

    Raises:
        ValueError: if the inputs are empty or unequal length.

    Notes:
        With n=1 paired run the bootstrap distribution is degenerate (every
        resample is the single delta), so the CI collapses to that delta and
        `excludes_zero` reflects whether that single delta is non-zero. Callers
        that need a real interval should require n >= 2 before trusting the CI.
    """
    w = list(with_vals)
    o = list(without_vals)
    if not w or not o:
        raise ValueError("paired_bootstrap_ci: empty input(s)")
    if len(w) != len(o):
        raise ValueError(
            f"paired_bootstrap_ci: unequal lengths {len(w)} != {len(o)} "
            "(arms must be paired index-for-index)"
        )

    deltas = [a - b for a, b in zip(w, o)]
    n = len(deltas)
    delta_mean = sum(deltas) / n

    rng = random.Random(seed)
    boot_means = []
    for _ in range(n_boot):
        s = 0.0
        for _ in range(n):
            s += deltas[rng.randrange(n)]
        boot_means.append(s / n)
    boot_means.sort()

    lo_q = (1.0 - ci) / 2.0
    hi_q = 1.0 - lo_q
    ci_low = _percentile(boot_means, lo_q)
    ci_high = _percentile(boot_means, hi_q)

    if ci_low > 0.0:
        direction = "positive"
        excludes_zero = True
    elif ci_high < 0.0:
        direction = "negative"
        excludes_zero = True
    else:
        direction = "inconclusive"
        excludes_zero = False

    return {
        "delta_mean": round(delta_mean, 6),
        "ci_low": round(ci_low, 6),
        "ci_high": round(ci_high, 6),
        "excludes_zero": excludes_zero,
        "direction": direction,
        "n": n,
    }


def attach_ci(
    with_agg: dict,
    baseline_agg: dict,
    metric_keys: Sequence[str],
    n_boot: int = 10000,
    ci: float = 0.95,
    seed: int = 0,
) -> dict:
    """Annotate each metric of `with_agg` with a paired-bootstrap `ci95` field.

    Operates on the aggregate dicts produced by a grader's `aggregate_runs`,
    which (post-Phase-B) carry a per-metric `"values"` list of the raw per-run
    metric values for that arm. For every key in `metric_keys` where BOTH arms
    expose an equal-length, non-empty `"values"` list, this computes the paired
    CI of (with - baseline) per run and writes:

        with_agg[key]["ci95"] = {
            "low", "high", "excludes_zero", "direction", "n"
        }

    Metrics lacking paired per-run values (e.g. a metric that is None on one
    arm, or aggregates from a legacy results.json that predates the `"values"`
    field) are left untouched — so this is purely additive and degrades
    gracefully to the legacy delta-threshold verdict.

    Returns `with_agg` (mutated in place) for call-chaining convenience.
    """
    for k in metric_keys:
        wm = with_agg.get(k)
        bm = baseline_agg.get(k)
        if not isinstance(wm, dict) or not isinstance(bm, dict):
            continue
        wv = wm.get("values")
        bv = bm.get("values")
        if not wv or not bv or len(wv) != len(bv):
            continue
        res = paired_bootstrap_ci(wv, bv, n_boot=n_boot, ci=ci, seed=seed)
        wm["ci95"] = {
            "low": res["ci_low"],
            "high": res["ci_high"],
            "excludes_zero": res["excludes_zero"],
            "direction": res["direction"],
            "n": res["n"],
        }
    return with_agg


def ci_verdict(with_agg: dict, primary_metric: str, favorable: str = "higher") -> dict | None:
    """CI-aware KEEP / TRIM / BLOCKED verdict on `primary_metric`, or None.

    Reads the `ci95` field that `attach_ci` writes onto the with-skill
    aggregate's primary metric and applies the rule:

      * KEEP                 : CI excludes 0 in the FAVORABLE direction
                               (positive when `favorable="higher"`, negative
                               when `favorable="lower"`).
      * TRIM                 : CI excludes 0 in the UNFAVORABLE direction
                               (the framework makes the primary metric worse).
      * BLOCKED ON MEASUREMENT : CI straddles 0 — no current-state evidence the
                               framework helps or hurts (ship-discipline rule 10).

    Returns a verdict dict {verdict, primary_metric, ci95, reason} when a `ci95`
    field is present, or `None` when paired CI data is unavailable (the caller
    then falls back to its legacy delta-threshold logic). The returned dict is
    additive: callers merge it into / alongside their existing verdict schema.
    """
    metric = with_agg.get(primary_metric)
    if not isinstance(metric, dict):
        return None
    ci95 = metric.get("ci95")
    if not isinstance(ci95, dict):
        return None

    favorable_dir = "positive" if favorable == "higher" else "negative"
    unfavorable_dir = "negative" if favorable == "higher" else "positive"
    direction = ci95.get("direction")
    excludes_zero = bool(ci95.get("excludes_zero"))
    bounds = f"[{ci95.get('low')}, {ci95.get('high')}]"

    if excludes_zero and direction == favorable_dir:
        verdict = "keep"
        reason = (f"95% CI {bounds} on {primary_metric} excludes 0 in the favorable "
                  f"({favorable}-is-better) direction")
    elif excludes_zero and direction == unfavorable_dir:
        verdict = "trim"
        reason = (f"95% CI {bounds} on {primary_metric} excludes 0 in the UNFAVORABLE "
                  f"direction — framework degrades the primary metric")
    else:
        verdict = "BLOCKED ON MEASUREMENT"
        reason = (f"95% CI {bounds} on {primary_metric} straddles 0 — no current-state "
                  f"evidence the framework helps or hurts")
    return {"verdict": verdict, "primary_metric": primary_metric,
            "ci95": ci95, "reason": reason, "ci_aware": True}


def _percentile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolated percentile of an already-sorted list. q in [0,1]."""
    if not sorted_vals:
        raise ValueError("_percentile: empty input")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac
