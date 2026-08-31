#!/usr/bin/env python3
"""Pure, key-free scorer for the evaluate-repos live-arm efficacy harness.

See harness/PROBLEM.md. evaluate-repos exists to fix self-evaluation DISMISSAL bias,
so this grader measures DECISION ACCURACY and especially FALSE-DISMISSAL RATE (a
should_adopt pattern that the arm REJECTed/DEFERred), comparing the advocate/skeptic
harness vs a single self-eval pass. NO network/API calls.

Anti-circularity: dispositions are HUMAN-CURATED historical ground truth; the producer
never judges itself.
"""
from __future__ import annotations

import re
import statistics
import sys
from pathlib import Path

# CI-aware verdict support (Phase B). _shared/stats.py is stdlib-only and key-free.
_SHARED = Path(__file__).resolve().parents[2] / "_shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))
try:
    import stats  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover - defensive: never break scoring on import issues
    stats = None  # type: ignore

# Higher-is-better primary metric for the CI-aware verdict (paired with vs baseline).
# The stated value-prop (lower false_dismissal_rate) is a lower-is-better metric kept
# as a legacy `fix`/keep guard below; the CI rule governs on decision_accuracy.
_CI_PRIMARY_METRIC = "decision_accuracy"

_WS = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    return _WS.sub(" ", (s or "").lower()).strip()


def normalize_decision(raw: str) -> str:
    """Map a free-form decision to ADOPT / DEFER / REJECT. Negations checked first."""
    v = normalize_text(raw)
    # explicit reject
    if any(c in v for c in ("reject", "do not adopt", "don't adopt", "should not adopt",
                            "against adopt", "not worth adopting", "decline")):
        return "REJECT"
    if any(c in v for c in ("defer", "wait", "monitor", "revisit", "later", "hold off",
                            "not yet", "table it", "needs more")):
        return "DEFER"
    if any(c in v for c in ("adopt", "implement it", "should implement", "integrate it",
                            "yes, adopt", "in favor")):
        return "ADOPT"
    return "DEFER"  # non-committal default


def _rate(num, denom):
    return (num / denom) if denom else None


def score_run(fixture: dict, records: list[dict]) -> dict:
    by_id = {p["id"]: p for p in fixture["patterns"]}
    rows = []
    for r in records:
        p = by_id[r["id"]]
        dec = normalize_decision(r.get("decision", ""))
        disp = p["disposition"]
        correct = (dec == "ADOPT" and disp == "should_adopt") or (dec == "REJECT" and disp == "should_reject")
        rows.append({"id": r["id"], "disposition": disp, "look_dismissable": p.get("look_dismissable", False),
                     "decision": dec, "correct": correct})

    adopt = [x for x in rows if x["disposition"] == "should_adopt"]
    reject = [x for x in rows if x["disposition"] == "should_reject"]
    dismissable = [x for x in adopt if x["look_dismissable"]]

    return {
        "n": len(rows),
        "decision_accuracy": _rate(sum(x["correct"] for x in rows), len(rows)),
        # KEY: of should_adopt, fraction NOT adopted (rejected or deferred) = dismissed.
        "false_dismissal_rate": _rate(sum(1 for x in adopt if x["decision"] != "ADOPT"), len(adopt)),
        # hard rejects only (stronger signal of the bias)
        "hard_reject_rate": _rate(sum(1 for x in adopt if x["decision"] == "REJECT"), len(adopt)),
        # the de-bias-critical subset: should_adopt patterns that LOOK dismissable
        "dismissable_dismissal_rate": _rate(sum(1 for x in dismissable if x["decision"] != "ADOPT"),
                                            len(dismissable)),
        # guard against over-correction: of should_reject, fraction wrongly adopted
        "over_adoption_rate": _rate(sum(1 for x in reject if x["decision"] == "ADOPT"), len(reject)),
        "rows": rows,
    }


_METRIC_KEYS = ("decision_accuracy", "false_dismissal_rate", "hard_reject_rate",
                "dismissable_dismissal_rate", "over_adoption_rate")


def aggregate_runs(run_metrics: list[dict]) -> dict:
    out: dict = {"n_runs": len(run_metrics)}
    for k in _METRIC_KEYS:
        vals = [m[k] for m in run_metrics if m.get(k) is not None]
        if vals:
            out[k] = {"mean": round(statistics.mean(vals), 4), "min": round(min(vals), 4),
                      "max": round(max(vals), 4),
                      "stdev": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0, "n": len(vals),
                      # per-run values retained so attach_ci can compute a paired CI (Phase B).
                      "values": [round(v, 4) for v in vals]}
        else:
            out[k] = None
    return out


def decide_verdict(with_skill: dict, baseline: dict, min_delta: float = 0.05) -> dict:
    """keep / trim / fix on the de-bias claim.

    The claim: the advocate/skeptic harness LOWERS false-dismissal vs a single
    self-eval pass without inflating over-adoption.
      keep : harness false_dismissal is LOWER than baseline by more than the noise
             floor AND harness over_adoption is not meaningfully worse.
      fix  : harness OVER-ADOPTS (over-correction) — over_adoption worse than baseline
             by more than noise (the de-biasing went too far, now accepting bad patterns).
      trim : harness false_dismissal ~ baseline (no measurable de-bias) — the
             multi-agent cost isn't buying lower false-dismissal.
    """
    def m(d, k):
        return (d.get(k) or {}).get("mean")

    def std(d, k):
        return (d.get(k) or {}).get("stdev", 0.0) or 0.0

    fd_w, fd_b = m(with_skill, "false_dismissal_rate"), m(baseline, "false_dismissal_rate")
    oa_w, oa_b = m(with_skill, "over_adoption_rate"), m(baseline, "over_adoption_rate")
    if fd_w is None or fd_b is None:
        return {"verdict": "inconclusive", "reason": "missing false_dismissal_rate"}
    fd_noise = max(min_delta, std(with_skill, "false_dismissal_rate"))
    oa_noise = max(min_delta, std(with_skill, "over_adoption_rate"))
    fd_delta = round(fd_b - fd_w, 4)  # positive = harness dismisses LESS (good)

    # over-correction check (de-biasing went too far -> accepts bad patterns)
    if oa_w is not None and oa_b is not None and (oa_w - oa_b) > oa_noise:
        return {"verdict": "fix", "reason": f"harness OVER-ADOPTS: over_adoption {oa_w} vs baseline "
                f"{oa_b} (de-biasing over-corrected into accepting bad patterns)",
                "false_dismissal_delta": fd_delta, "over_adoption_with": oa_w}
    # BACKFIRE check: the de-bias mechanism makes false-dismissal WORSE than baseline
    # (e.g. the skeptic's mandatory AGAINST case pushes the decider to over-hedge/DEFER).
    if (fd_w - fd_b) > fd_noise:
        return {"verdict": "fix", "reason": f"de-bias BACKFIRES: harness false_dismissal {fd_w} is "
                f"HIGHER than single-pass {fd_b} by {round(fd_w - fd_b, 4)} (the advocate/skeptic "
                f"step INCREASED dismissal rather than reducing it — over-hedging)",
                "false_dismissal_delta": fd_delta}

    # CI-aware rule (Phase B): the genuine `fix` mechanism checks above (over-adoption,
    # de-bias backfire) still take precedence. Past them, when paired per-run CI is
    # available on decision_accuracy, the CI verdict GOVERNS the keep/trim/BLOCKED
    # decision. Legacy false_dismissal-threshold below is the fallback when no CI.
    if stats is not None:
        civ = stats.ci_verdict(with_skill, _CI_PRIMARY_METRIC, favorable="higher")
        if civ is not None:
            civ.update({"false_dismissal_delta": fd_delta, "legacy_min_delta": min_delta})
            return civ

    if fd_delta > fd_noise:
        return {"verdict": "keep", "reason": f"harness LOWERS false-dismissal by {fd_delta} "
                f"(harness {fd_w} vs single-pass {fd_b}) beyond noise {round(fd_noise,3)}; "
                f"de-bias claim supported", "false_dismissal_delta": fd_delta}
    return {"verdict": "trim", "reason": f"false-dismissal delta {fd_delta} within noise "
            f"({round(fd_noise,3)}) — harness {fd_w} ~ single-pass {fd_b}; multi-agent cost not "
            f"buying measurable de-bias", "false_dismissal_delta": fd_delta}
