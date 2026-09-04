#!/usr/bin/env python3
"""Pure, key-free scorer for the deep-dive live-arm efficacy harness.

See harness/PROBLEM.md. deep-dive's value-prop is the three-layer defense
(HIGH/MEDIUM/LOW confidence + provenance + per-finding counterfactual), so this
grader measures ANSWER CORRECTNESS + CONFIDENCE CALIBRATION (do HIGH-confidence
answers come true more than LOW?) + COUNTERFACTUAL substance — NOT grounding.

NO network/API calls. run_live.py imports this to score each live A/B run,
regrade.py re-scores saved records offline, and tests/test_deep_dive_efficacy.py
unit-tests it (FP=FN=0) + asserts results.json.

Anti-circularity: correctness is checked against HUMAN-CURATED answer keys
(deterministic term match); the producer never judges itself.

Revision 2026-09-03 (docs/research-skills-root-cause.md section 4): the Fable 5.1
rerun exposed three instrument defects, corrected here without touching the frozen
2026-05-31 results.json (the committed 2026-05-31 sample re-grades identically):
  1. DATED KEYS. Currency questions carry a `keys` list of answer keys with
     [valid_from, valid_until] windows; `score_run` grades against the key in force
     on `run_date` and EXCLUDES a question whose keys have all expired instead of
     grading it against a stale answer (`current-anthropic-model` failed 3 correct
     answers this way).
  2. REJECTION CUES. `_REJECTION_CUES` gained the phrasings observed in the rerun
     ("premise is false", "No 2025 result ...", a leading "None."); the v1 list
     false-failed 4 correct rejections of `cot-faithfulness-solved`.
  3. CALIBRATION OVER FACT QUESTIONS ONLY. `SYSTEM_WITH` tells the arm to answer
     LOW when the premise is dubious, and the grader scores a rejection as correct,
     so LOW-on-rejection filled the non-HIGH bin with correct answers and pushed
     discrimination negative by construction. `calibration_discrimination` is now
     computed over `fact` rows; `calibration_discrimination_all` keeps the legacy
     all-kinds view for comparison.

Revision 2026-09-04: the `current-anthropic-model` key is no longer typed by hand.
run_live.py snapshots the vendor's model list at run start (`model_catalog`, newest
first) and records it in the run receipt and the transcripts; `catalog_key` derives the
expected terms from the newest release's display name, so the key is whatever the vendor
served THAT DAY and re-grading stays offline. The dated `keys` remain only as the fallback
for records made before snapshots existed (the second window is marked `legacy`).
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
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def normalize_text(s: str) -> str:
    return _WS.sub(" ", (s or "").lower()).strip()


_REJECTION_CUES = (
    "no such", "does not exist", "doesn't exist", "not aware", "cannot find",
    "can't find", "no record", "fabricat", "not a real", "unable to verify",
    "no evidence", "no published", "i'm not aware", "not aware of any",
    "does not appear to exist", "no widely", "not a recognized", "no official",
    "false premise", "incorrect premise", "not been solved", "has not been solved",
    "no benchmark", "no paper", "no anthropic", "not exist",
    # 2026-09-03 revision: forms observed in the Fable 5.1 rerun that the list above
    # missed (4 correct rejections of `cot-faithfulness-solved` were false-failed).
    "premise is false", "premise of the question is false", "premise is incorrect",
    "no 2025 result", "no result exists", "no such result", "no result has",
    "not solved", "unsolved", "open problem", "open research problem",
    "remains an open", "remains open", "could not find", "did not find",
    "no paper, benchmark",
)
# A false-premise answer that OPENS with a bare "None." / "No such ..." / "No <year>
# result ..." is a rejection regardless of the phrasing that follows. Deliberately
# narrow: "No, but ..." and "Novel ..." do not match; they fall through to the cues.
_REJECTION_LEAD = re.compile(
    r"^\s*(?:none\b|no\s+(?:such|result|results|\d{4}|paper|benchmark|published|"
    r"official|peer|known|single|definitive|anthropic)\b)"
)


def _has_any(terms: Iterable[str], hay: str) -> bool:
    return any(normalize_text(t) in hay for t in terms if t and t.strip())


def rejects_premise(answer_text: str) -> bool:
    """Deterministic: does a false-premise answer REJECT the premise?"""
    hay = normalize_text(answer_text)
    if not hay:
        return False
    if _REJECTION_LEAD.match(hay):
        return True
    return any(cue in hay for cue in _REJECTION_CUES)


def catalog_key(model_catalog: list[dict]) -> dict:
    """Answer key derived from the run's own snapshot of the vendor model list.

    The snapshot (run_live.fetch_model_catalog) holds {id, display_name, created_at}
    per model. The key's expected terms are the display-name tokens of every model
    released on the NEWEST date, minus the vendor word: "Claude Fable 5.1" gives
    ["fable 5.1", "fable"], and a paired launch (Fable + Mythos on one day) names both.
    No hand-typed world fact is involved, so the key cannot go stale between fixture
    revisions. Assumption: the newest release is the most capable family; if a lower
    tier ships later, `derived_from` in the recorded key shows it and the question must
    be re-keyed by hand.
    """
    rows = [m for m in model_catalog if isinstance(m, dict) and m.get("id")]
    if not rows:
        raise ValueError("model catalog is empty; cannot derive the current-model key")
    newest_date = max(str(m.get("created_at") or "")[:10] for m in rows)
    newest = sorted((m for m in rows if str(m.get("created_at") or "")[:10] == newest_date),
                    key=lambda m: m["id"])
    terms: list[str] = []
    for m in newest:
        name = normalize_text(str(m.get("display_name") or ""))
        if not name:  # fall back to the id: claude-fable-5-1 -> "fable 5 1"
            name = normalize_text(m["id"].removeprefix("claude-").replace("-", " "))
        words = [w for w in name.split() if w != "claude"]
        for term in (" ".join(words), " ".join(w for w in words if w.isalpha())):
            if term and term not in terms:
                terms.append(term)
    return {"source": "model-catalog", "derived_from": [m["id"] for m in newest],
            "released": newest_date, "verified": None,
            "expected_terms": terms, "wrong_terms": []}


def key_source(question: dict, model_catalog: list[dict] | None = None) -> str:
    """Which key path grades this question: model-catalog, dated (legacy fallback) or static."""
    if question.get("key_source") == "model-catalog" and model_catalog:
        return "model-catalog"
    return "dated" if question.get("keys") else "static"


def key_for(question: dict, run_date: str | None, model_catalog: list[dict] | None = None) -> dict | None:
    """Select the answer key in force on `run_date`.

    Questions without `keys` use their static expected_terms/wrong_terms (run_date is
    ignored). A question with `key_source: model-catalog` is graded against
    `catalog_key(model_catalog)` whenever the run recorded a snapshot; its dated `keys`
    are the fallback for records made before snapshots existed. Other questions with
    `keys` (dated currency questions) require run_date; the key whose
    [valid_from, valid_until] window (ISO dates, inclusive, null = open) contains it is
    returned. None means every key has expired for that run date: the question is
    EXCLUDED from scoring rather than graded against a stale answer.
    """
    if key_source(question, model_catalog) == "model-catalog":
        return catalog_key(model_catalog)  # type: ignore[arg-type]
    keys = question.get("keys")
    if not keys:
        return {"expected_terms": question.get("expected_terms", []),
                "wrong_terms": question.get("wrong_terms", [])}
    if not isinstance(run_date, str) or not _ISO_DATE.match(run_date):
        raise ValueError(
            f"question {question.get('id')!r} has dated keys; score_run needs "
            f"run_date='YYYY-MM-DD' (got {run_date!r})")
    for key in keys:
        lo, hi = key.get("valid_from"), key.get("valid_until")
        if (lo is None or lo <= run_date) and (hi is None or run_date <= hi):
            return key
    return None


def answer_correct(question: dict, answer_text: str, run_date: str | None = None,
                   model_catalog: list[dict] | None = None) -> bool | None:
    """Deterministic correctness vs the human-curated (or catalog-derived) key.

    Returns None when the question's dated keys have all expired for `run_date`
    (the caller excludes it); otherwise a bool."""
    hay = normalize_text(answer_text)
    if question["kind"] == "false_premise":
        # correct iff the answer REJECTS the false premise
        return rejects_premise(hay)
    key = key_for(question, run_date, model_catalog)
    if key is None:
        return None
    if not hay:
        return False
    # kind == "fact": >=1 expected term present AND no stale/wrong term present
    return (_has_any(key.get("expected_terms", []), hay)
            and not _has_any(key.get("wrong_terms", []), hay))


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


def _discrimination(rows: list[dict]) -> tuple[float | None, float | None, float | None]:
    high = [x for x in rows if x["confidence"] == "HIGH"]
    nonhigh = [x for x in rows if x["confidence"] != "HIGH"]
    acc_high = _rate(sum(x["correct"] for x in high), len(high))
    acc_nonhigh = _rate(sum(x["correct"] for x in nonhigh), len(nonhigh))
    disc = (acc_high - acc_nonhigh) if (acc_high is not None and acc_nonhigh is not None) else None
    return acc_high, acc_nonhigh, disc


def score_run(fixture: dict, records: list[dict], run_date: str | None = None,
              model_catalog: list[dict] | None = None) -> dict:
    """records: [{id, answer_text, confidence, counterfactual}]. counterfactual
    may be absent (baseline produces none). run_date ('YYYY-MM-DD') selects the
    dated answer key for currency questions; required when the fixture has any.
    model_catalog is the run's recorded vendor model list; when present it grades the
    `key_source: model-catalog` question instead of its dated (legacy) keys."""
    by_id = {q["id"]: q for q in fixture["questions"]}
    all_cfs = [r.get("counterfactual", "") or "" for r in records]
    rows = []
    for r in records:
        q = by_id[r["id"]]
        correct = answer_correct(q, r.get("answer_text", ""), run_date, model_catalog)
        conf = normalize_confidence(r.get("confidence", ""))
        cf = r.get("counterfactual", "") or ""
        rows.append({
            "id": r["id"], "kind": q["kind"], "difficulty": q.get("difficulty"),
            "currency": q.get("currency", False), "correct": correct,
            "key_expired": correct is None,
            "key_source": key_source(q, model_catalog),
            "confidence": conf,
            "cf_substantive": counterfactual_substantive(cf, all_cfs) if cf else None,
        })

    scored = [x for x in rows if not x["key_expired"]]
    fact_rows = [x for x in scored if x["kind"] == "fact"]
    acc_high, acc_nonhigh, discrimination = _discrimination(fact_rows)
    _, _, discrimination_all = _discrimination(scored)
    cfs_present = [x for x in rows if x["cf_substantive"] is not None]

    return {
        "n": len(rows),
        "n_scored": len(scored),
        "n_key_expired": len(rows) - len(scored),
        "key_expired_ids": sorted({x["id"] for x in rows if x["key_expired"]}),
        "accuracy": _rate(sum(x["correct"] for x in scored), len(scored)),
        "acc_high": acc_high,
        "acc_nonhigh": acc_nonhigh,
        # KEY metric: do HIGH-confidence FACT answers come true more than non-HIGH ones?
        # (false-premise rows are excluded: a LOW label on a correct rejection is the
        # framework following its own prompt, not a calibration failure)
        "calibration_discrimination": round(discrimination, 4) if discrimination is not None else None,
        # legacy all-kinds view (pre-2026-09-03 definition), for comparison only
        "calibration_discrimination_all": round(discrimination_all, 4) if discrimination_all is not None else None,
        "high_share": _rate(sum(1 for x in scored if x["confidence"] == "HIGH"), len(scored)),
        "currency_accuracy": _rate(sum(x["correct"] for x in scored if x["currency"]),
                                   sum(1 for x in scored if x["currency"])),
        "false_premise_reject_rate": _rate(
            sum(x["correct"] for x in rows if x["kind"] == "false_premise"),
            sum(1 for x in rows if x["kind"] == "false_premise")),
        "counterfactual_substantive_rate": _rate(sum(1 for x in cfs_present if x["cf_substantive"]),
                                                  len(cfs_present)) if cfs_present else None,
        "rows": rows,
    }


_METRIC_KEYS = ("accuracy", "calibration_discrimination", "currency_accuracy",
                "false_premise_reject_rate", "counterfactual_substantive_rate")


def aggregate_runs(run_metrics: list[dict], keys: Iterable[str] = _METRIC_KEYS) -> dict:
    out: dict = {"n_runs": len(run_metrics)}
    for k in keys:
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
