#!/usr/bin/env python3
"""Pure, key-free scoring for the gather-intel live-arm efficacy harness.

See harness/PROBLEM.md. This module contains NO network/API calls — it is the
deterministic instrument that:
  - run_live.py imports to score each live A/B run, and
  - tests/test_gather_intel_efficacy.py unit-tests on a tiny synthetic
    fixture (Phase 2: prove the instrument FP=FN=0) AND asserts the committed
    results.json against.

Anti-circularity: the grader compares an arm's output against the HUMAN-CURATED
fixture labels + a DETERMINISTIC term-overlap grounding signal. No model judges
the producer's output (cardinal rule).
"""
from __future__ import annotations

import re
import statistics
import sys
from pathlib import Path
from typing import Iterable

# CI-aware verdict support (Phase B). _shared/stats.py is stdlib-only and key-free.
_SHARED = Path(__file__).resolve().parents[2] / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))
try:
    import stats  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover - defensive: never break scoring on import issues
    stats = None  # type: ignore

# ---- text + grounding -------------------------------------------------------

_WS = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    """Lowercase + collapse all whitespace runs to single spaces."""
    return _WS.sub(" ", (s or "").lower()).strip()


def grounding_passes(grounding_terms: Iterable[str], page_text: str,
                     threshold: float = 0.6) -> bool:
    """True iff >= threshold fraction of grounding_terms appear in page_text.

    Deterministic, case-insensitive, whitespace-normalized substring test.
    For true_primary claims a genuinely supporting page contains the terms;
    for fabricated claims NO real page contains the fabricated title/author/
    stat, so a citation to an adjacent real paper fails this check.
    """
    terms = [normalize_text(t) for t in grounding_terms if t and t.strip()]
    if not terms:
        return False
    hay = normalize_text(page_text)
    if not hay:
        return False
    hits = sum(1 for t in terms if t in hay)
    return (hits / len(terms)) >= threshold


# ---- verdict normalization --------------------------------------------------

# An arm emits a free-form verdict label; collapse it to the binary disposition
# the oracle scores against. Order matters: explicit negations are checked first.
_NOT_SUPPORTED_CUES = (
    "not supported", "not_supported", "unsupported", "no support",
    "refuted", "contested", "outdated", "stale", "superseded",
    "uncharted", "fabricated", "false", "incorrect", "not true", "untrue",
    "no source", "no primary", "cannot verify", "can't verify", "unverifi",
    "no evidence", "debunk",
)
_SUPPORTED_CUES = (
    "supported", "support", "true", "confirmed", "grounded", "verified",
    "accurate", "correct", "primary",
)


def normalize_verdict(raw_verdict: str) -> str:
    """Map a free-form verdict string to {'supported','not_supported'}.

    Negation cues win (so 'NOT SUPPORTED' / 'unsupported' / 'not true' do not
    fall through to the 'support'/'true' substrings). Anything that matches no
    cue is treated as not_supported (a non-committal answer is not a SUPPORTED
    assertion).
    """
    v = normalize_text(raw_verdict)
    for cue in _NOT_SUPPORTED_CUES:
        if cue in v:
            return "not_supported"
    for cue in _SUPPORTED_CUES:
        if cue in v:
            return "supported"
    return "not_supported"


# ---- scoring one run --------------------------------------------------------

def _rate(num: int, denom: int):
    return (num / denom) if denom else None


def score_run(fixture: dict, records: list[dict]) -> dict:
    """Score one arm's run of the whole fixture.

    `records`: list of {id, raw_verdict, cited_urls(list), grounded(bool|None)}.
    `grounded` is computed upstream by run_live.py (fetch cited URL ->
    grounding_passes); for not_supported verdicts it is irrelevant (None).
    Returns metrics + per-claim rows.
    """
    by_id = {c["id"]: c for c in fixture["claims"]}
    rows = []
    for r in records:
        c = by_id[r["id"]]
        nv = normalize_verdict(r["raw_verdict"])
        supported = nv == "supported"
        # A "supported" assertion grounds only if it cites a URL whose fetched
        # text passes the term check. No citation => not grounded.
        grounded = bool(r.get("grounded")) if supported else None
        rows.append({
            "id": r["id"],
            "category": c["category"],
            "expected": c["expected_disposition"],
            "raw_verdict": r["raw_verdict"],
            "norm_verdict": nv,
            "correct": nv == c["expected_disposition"],
            "cited_urls": r.get("cited_urls", []),
            "grounded": grounded,
        })

    def subset(cats):
        return [x for x in rows if x["category"] in cats]

    supported_rows = [x for x in rows if x["norm_verdict"] == "supported"]
    grounded_supported = [x for x in supported_rows if x["grounded"]]

    refuted_outdated = subset({"refuted", "outdated"})
    fabricated = subset({"fabricated"})
    true_rows = subset({"true_primary"})

    return {
        "n_claims": len(rows),
        # precision-sensitive view: of everything the arm asserted SUPPORTED,
        # what fraction is backed by a citation that actually grounds.
        "grounding_precision": _rate(len(grounded_supported), len(supported_rows)),
        "n_supported": len(supported_rows),
        "n_grounded_supported": len(grounded_supported),
        # recall-sensitive view: stale/false claims correctly downgraded.
        "refutation_recall": _rate(
            sum(1 for x in refuted_outdated if x["norm_verdict"] == "not_supported"),
            len(refuted_outdated)),
        # fabricated claims correctly NOT asserted (inverse hallucination rate).
        "fabrication_resistance": _rate(
            sum(1 for x in fabricated if x["norm_verdict"] == "not_supported"),
            len(fabricated)),
        # guard against over-correction: true claims still confirmed.
        "true_recall": _rate(
            sum(1 for x in true_rows if x["norm_verdict"] == "supported"),
            len(true_rows)),
        "verdict_accuracy": _rate(sum(1 for x in rows if x["correct"]), len(rows)),
        "rows": rows,
    }


# ---- aggregating N runs -----------------------------------------------------

_METRIC_KEYS = ("grounding_precision", "refutation_recall",
                "fabrication_resistance", "true_recall", "verdict_accuracy")


def aggregate_runs(run_metrics: list[dict]) -> dict:
    """mean + spread (min/max/stdev) per metric across N runs of one arm."""
    out: dict = {"n_runs": len(run_metrics)}
    for k in _METRIC_KEYS:
        vals = [m[k] for m in run_metrics if m.get(k) is not None]
        if vals:
            out[k] = {
                "mean": round(statistics.mean(vals), 4),
                "min": round(min(vals), 4),
                "max": round(max(vals), 4),
                "stdev": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0,
                "n": len(vals),
                # per-run values retained so attach_ci can compute a paired CI (Phase B).
                "values": [round(v, 4) for v in vals],
            }
        else:
            out[k] = None
    return out


def decide_verdict(with_skill: dict, baseline: dict, primary_metric: str,
                   cost_ratio: float, min_delta: float = 0.05) -> dict:
    """keep / trim / fix on the primary value-prop metric.

    keep  : with-skill mean exceeds baseline by a margin that justifies the
            framework's cost (delta >= min_delta AND clears the noise floor).
    trim  : delta small / negative — framework not worth the ceremony.
    fix   : a specific value-dimension underperforms the baseline by more than
            the noise floor (the framework actively makes something WORSE), even
            if the primary metric is flat — i.e. there is a fixable mechanism.

    NB: this copy (a) adds `true_recall` to the regression set — over-rejecting
    genuine items is a first-class "fix" trigger (the gather-claude finding) —
    and (b) makes the regression bar NOISE-AWARE: a sub-metric counts as a
    regression only if (baseline - with_skill) exceeds max(min_delta, the
    with-skill metric's own N=3 stdev). At N=3 the per-metric stdev is ~0.07-0.09,
    so a flat 0.05 bar false-triggers on noise (gather-intel true_recall dipped
    0.067 < its 0.094 stdev = noise, not a real regression). gather-claude's 0.20
    true_recall drop (> its 0.094 stdev) stays correctly flagged.
    """
    def mean(d, k):
        return (d.get(k) or {}).get("mean")

    def stdev(d, k):
        return (d.get(k) or {}).get("stdev", 0.0) or 0.0

    w = mean(with_skill, primary_metric)
    b = mean(baseline, primary_metric)
    if w is None or b is None:
        return {"verdict": "inconclusive", "reason": f"missing {primary_metric}"}
    delta = round(w - b, 4)

    # CI-aware rule (Phase B): when paired per-run CI is available on the primary
    # metric, the CI verdict GOVERNS (KEEP iff CI excludes 0 favorable, TRIM iff
    # excludes 0 unfavorable, else BLOCKED ON MEASUREMENT). Legacy delta-threshold
    # below is the fallback ONLY when paired runs are unavailable (no ci95 field).
    if stats is not None:
        civ = stats.ci_verdict(with_skill, primary_metric, favorable="higher")
        if civ is not None:
            civ.update({"delta": delta, "cost_ratio": cost_ratio,
                        "legacy_min_delta": min_delta})
            return civ

    # sub-metric regression check: framework makes a value-dimension worse by more
    # than the noise floor (max of min_delta and the with-skill metric's N=3 stdev).
    regressions = []
    for k in ("refutation_recall", "fabrication_resistance", "grounding_precision", "true_recall"):
        wk, bk = mean(with_skill, k), mean(baseline, k)
        if wk is not None and bk is not None and (bk - wk) > max(min_delta, stdev(with_skill, k)):
            regressions.append(k)

    if delta >= min_delta:
        return {"verdict": "keep", "primary_metric": primary_metric,
                "delta": delta, "cost_ratio": cost_ratio,
                "reason": f"+{delta} on {primary_metric} clears the {min_delta} bar"}
    if regressions:
        return {"verdict": "fix", "primary_metric": primary_metric, "delta": delta,
                "regressions": regressions,
                "reason": f"sub-metric(s) {regressions} regress vs baseline"}
    return {"verdict": "trim", "primary_metric": primary_metric, "delta": delta,
            "cost_ratio": cost_ratio,
            "reason": f"delta {delta} < {min_delta} bar — framework not worth "
                      f"its ~{cost_ratio}x cost"}
