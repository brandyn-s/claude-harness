#!/usr/bin/env python3
"""Pure, key-free scorer for the deep-dive live-arm efficacy harness.

See harness/PROBLEM.md. deep-dive's value-prop is the three-layer defense
(HIGH/MEDIUM/LOW confidence + provenance + per-finding counterfactual), so this
grader measures ANSWER CORRECTNESS + CONFIDENCE CALIBRATION (do HIGH-confidence
answers come true more than LOW?) + COUNTERFACTUAL substance — NOT grounding.

NO network/API calls. run_live.py imports this to score each live A/B run, and
tests/test_deep_dive_efficacy.py unit-tests it (FP=FN=0) + asserts results.json.

Anti-circularity: correctness is checked against HUMAN-CURATED answer keys
(deterministic term match); the producer never judges itself.
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

# Higher-is-better primary metric for the CI-aware verdict (paired with vs baseline).
# NB: deep-dive's bespoke value-prop is calibration_discrimination (a single-arm
# metric), which is NOT a paired with-vs-baseline delta. The CI rule therefore
# governs on `accuracy` (the paired correctness metric); the calibration/counterfactual
# regression checks below remain as legacy guards and still fire on a `fix` mechanism.
_CI_PRIMARY_METRIC = "accuracy"

_WS = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    return _WS.sub(" ", (s or "").lower()).strip()


_REJECTION_CUES = (
    "no such", "does not exist", "doesn't exist", "not aware", "cannot find",
    "can't find", "no record", "fabricat", "not a real", "unable to verify",
    "no evidence", "no published", "i'm not aware", "not aware of any",
    "does not appear to exist", "no widely", "not a recognized", "no official",
    "false premise", "incorrect premise", "not been solved", "has not been solved",
    "no benchmark", "no paper", "no anthropic", "not exist",
)


def _has_any(terms: Iterable[str], hay: str) -> bool:
    return any(normalize_text(t) in hay for t in terms if t and t.strip())


def answer_correct(question: dict, answer_text: str) -> bool:
    """Deterministic correctness vs the human-curated key."""
    hay = normalize_text(answer_text)
    if not hay:
        return False
    if question["kind"] == "false_premise":
        # correct iff the answer REJECTS the false premise
        return any(cue in hay for cue in _REJECTION_CUES)
    # kind == "fact": >=1 expected term present AND no stale/wrong term present
    return _has_any(question["expected_terms"], hay) and not _has_any(question.get("wrong_terms", []), hay)


def normalize_confidence(raw: str) -> str:
    v = normalize_text(raw)
    if "high" in v:
        return "HIGH"
    if "low" in v:
        return "LOW"
    if "medium" in v or "med" in v or "moderate" in v:
        return "MEDIUM"
    return "MEDIUM"  # unparseable -> treat as MEDIUM (non-committal)


_CF_VERDICT_CUES = ("survives", "collapses", "ambiguous")


def counterfactual_substantive(cf_text: str, all_cfs: list[str]) -> bool:
    """Substantive iff non-trivial length, carries a SURVIVES/COLLAPSES/AMBIGUOUS
    verdict (the skill's mandated form), and is not a duplicated boilerplate
    string repeated verbatim across questions."""
    t = normalize_text(cf_text)
    if len(t) < 40:
        return False
    if not any(c in t for c in _CF_VERDICT_CUES):
        return False
    # boilerplate detection: identical counterfactual reused across >1 question
    if sum(1 for x in all_cfs if normalize_text(x) == t) > 1:
        return False
    return True


def _rate(num, denom):
    return (num / denom) if denom else None


def score_run(fixture: dict, records: list[dict]) -> dict:
    """records: [{id, answer_text, confidence, counterfactual}]. counterfactual
    may be absent (baseline produces none)."""
    by_id = {q["id"]: q for q in fixture["questions"]}
    all_cfs = [r.get("counterfactual", "") or "" for r in records]
    rows = []
    for r in records:
        q = by_id[r["id"]]
        correct = answer_correct(q, r.get("answer_text", ""))
        conf = normalize_confidence(r.get("confidence", ""))
        cf = r.get("counterfactual", "") or ""
        rows.append({
            "id": r["id"], "kind": q["kind"], "difficulty": q.get("difficulty"),
            "currency": q.get("currency", False), "correct": correct,
            "confidence": conf,
            "cf_substantive": counterfactual_substantive(cf, all_cfs) if cf else None,
        })

    high = [x for x in rows if x["confidence"] == "HIGH"]
    nonhigh = [x for x in rows if x["confidence"] != "HIGH"]
    acc_high = _rate(sum(x["correct"] for x in high), len(high))
    acc_nonhigh = _rate(sum(x["correct"] for x in nonhigh), len(nonhigh))
    discrimination = (acc_high - acc_nonhigh) if (acc_high is not None and acc_nonhigh is not None) else None
    cfs_present = [x for x in rows if x["cf_substantive"] is not None]

    return {
        "n": len(rows),
        "accuracy": _rate(sum(x["correct"] for x in rows), len(rows)),
        "acc_high": acc_high,
        "acc_nonhigh": acc_nonhigh,
        # KEY metric: do HIGH-confidence answers come true more than non-HIGH?
        "calibration_discrimination": round(discrimination, 4) if discrimination is not None else None,
        "high_share": _rate(len(high), len(rows)),
        "currency_accuracy": _rate(sum(x["correct"] for x in rows if x["currency"]),
                                   sum(1 for x in rows if x["currency"])),
        "false_premise_reject_rate": _rate(
            sum(x["correct"] for x in rows if x["kind"] == "false_premise"),
            sum(1 for x in rows if x["kind"] == "false_premise")),
        "counterfactual_substantive_rate": _rate(sum(1 for x in cfs_present if x["cf_substantive"]),
                                                  len(cfs_present)) if cfs_present else None,
        "rows": rows,
    }


_METRIC_KEYS = ("accuracy", "calibration_discrimination", "currency_accuracy",
                "false_premise_reject_rate", "counterfactual_substantive_rate")


def aggregate_runs(run_metrics: list[dict]) -> dict:
    out: dict = {"n_runs": len(run_metrics)}
    for k in _METRIC_KEYS:
        vals = [m[k] for m in run_metrics if m.get(k) is not None]
        if vals:
            out[k] = {"mean": round(statistics.mean(vals), 4), "min": round(min(vals), 4),
                      "max": round(max(vals), 4),
                      "stdev": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0,
                      "n": len(vals),
                      # per-run values retained so attach_ci can compute a paired CI (Phase B).
                      "values": [round(v, 4) for v in vals]}
        else:
            out[k] = None
    return out


def decide_verdict(with_skill: dict, baseline: dict, min_delta: float = 0.05) -> dict:
    """keep / trim / fix for deep-dive.

    The value-prop is CALIBRATED CONFIDENCE + substantive counterfactuals, not
    raw correctness (a strong model + search ceilings correctness). So:
      keep : the framework's confidence MEANINGFULLY discriminates correctness
             (calibration_discrimination > min_delta, beyond noise) AND its
             counterfactuals are mostly substantive AND correctness is not worse
             than baseline. The framework adds calibration the baseline lacks.
      fix  : confidence is ANTI-calibrated (HIGH less accurate than non-HIGH;
             discrimination < -min_delta) OR counterfactuals are boilerplate
             (<50% substantive) — a specific mechanism underperforms.
      trim : confidence discrimination ~0 (labels are noise) and no clear
             correctness gain — the ceremony is not buying calibrated confidence.
    """
    def m(d, k):
        return (d.get(k) or {}).get("mean")

    disc = m(with_skill, "calibration_discrimination")
    cf = m(with_skill, "counterfactual_substantive_rate")
    acc_w, acc_b = m(with_skill, "accuracy"), m(baseline, "accuracy")
    disc_std = (with_skill.get("calibration_discrimination") or {}).get("stdev", 0.0) or 0.0
    noise = max(min_delta, disc_std)

    if disc is not None and disc < -noise:
        return {"verdict": "fix", "reason": f"confidence ANTI-calibrated: HIGH answers less "
                f"accurate than non-HIGH (discrimination {disc} < -{round(noise,3)})",
                "calibration_discrimination": disc}
    if cf is not None and cf < 0.5:
        return {"verdict": "fix", "reason": f"counterfactuals mostly boilerplate "
                f"(substantive rate {cf} < 0.5)", "counterfactual_substantive_rate": cf}

    # CI-aware rule (Phase B): the genuine `fix` mechanism checks above (anti-calibration,
    # boilerplate counterfactuals) still take precedence. Past them, when paired per-run CI
    # is available on the primary correctness metric, the CI verdict GOVERNS the keep/trim/
    # BLOCKED decision. Legacy discrimination-threshold below is the fallback when no CI.
    if stats is not None:
        civ = stats.ci_verdict(with_skill, _CI_PRIMARY_METRIC, favorable="higher")
        if civ is not None:
            civ["calibration_discrimination"] = disc
            civ["legacy_min_delta"] = min_delta
            return civ

    if disc is not None and disc > noise and (acc_w is None or acc_b is None or acc_w + 1e-9 >= acc_b):
        return {"verdict": "keep", "reason": f"confidence discriminates correctness "
                f"(HIGH-vs-nonHIGH accuracy gap {disc} > {round(noise,3)}); framework adds "
                f"calibrated confidence the baseline lacks", "calibration_discrimination": disc}
    return {"verdict": "trim", "reason": f"confidence discrimination {disc} within noise "
            f"({round(noise,3)}); labels not buying calibrated confidence",
            "calibration_discrimination": disc}
