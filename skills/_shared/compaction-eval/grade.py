#!/usr/bin/env python3
"""Pure, key-free grader for the compaction A/B (run_live.py).

Each fixture question is answered from the SUMMARY ONLY by a reader model and
then checked here by string or number match against fixture.py's planted key.
No model judges another model's output; the producer never grades itself.

Match rules (all case-insensitive, whitespace-collapsed, curly quotes unified):
  contains  any key phrase is a substring of the answer
  sha       the key sha, or at least its first 7 hex chars, appears as a token
  number    the key integer appears as a standalone integer (commas removed)
  verbatim  the whole key string is a substring of the answer
  label     exactly the expected label appears, and no other label from the set
  fileline  `basename:line` (or `basename line N`) appears
  decision  a chosen-option phrase appears, no wrong-choice phrase appears, and
            at least one reason phrase appears
An answer of UNKNOWN (what the reader is told to say when the summary lacks the
fact) is always wrong: the point is recall, not the reader's honesty.

NO network/API calls. Imports only the stdlib and skills/_shared/stats.py.
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

_SHARED = Path(__file__).resolve().parents[1]
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))
try:
    import stats  # type: ignore  # noqa: E402
except Exception:  # pragma: no cover - never break scoring on import trouble
    stats = None  # type: ignore

PRIMARY_METRIC = "recall"
CATEGORIES = ("identifiers", "errors", "questions", "root_causes", "hypotheses", "decisions", "subagent")
METRIC_KEYS = (PRIMARY_METRIC,) + tuple(f"recall_{c}" for c in CATEGORIES)

_WS = re.compile(r"\s+")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "`": ""})


def normalize(s: str) -> str:
    return _WS.sub(" ", (s or "").translate(_QUOTES).lower()).strip()


def is_unknown(s: str) -> bool:
    n = normalize(s).strip(" .\"'")
    return n == "" or n == "unknown" or n.startswith("unknown")


def match_contains(text: str, answers: list[str]) -> bool:
    n = normalize(text)
    return any(normalize(a) in n for a in answers if a)


def match_sha(text: str, answers: list[str]) -> bool:
    low = text.lower()
    return any(re.search(r"(?<![0-9a-f])" + re.escape(a.lower()[:7]) + r"[0-9a-f]*(?![0-9a-f])", low)
               for a in answers if len(a) >= 7)


def match_number(text: str, answers: list[str]) -> bool:
    flat = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text or "")
    return any(re.search(r"(?<!\d)" + re.escape(a) + r"(?!\d)", flat) for a in answers)


def match_verbatim(text: str, answers: list[str]) -> bool:
    n = normalize(text)
    return any(normalize(a) in n for a in answers)


def match_label(text: str, answers: list[str], labels: list[str]) -> bool:
    n = re.sub(r"[_-]", " ", normalize(text))
    found = {lab for lab in labels
             if re.search(r"\b" + re.escape(re.sub(r"[_-]", " ", lab.lower())) + r"\b", n)}
    return found == {answers[0]}


def match_fileline(text: str, answers: list[str]) -> bool:
    low = normalize(text)
    for a in answers:
        path, _, line = a.rpartition(":")
        base = path.rsplit("/", 1)[-1]
        if re.search(re.escape(base.lower()) + r"[,:\s]*(?:line\s*|l\.?\s*)?" + re.escape(line) + r"(?!\d)", low):
            return True
    return False


def match_decision(text: str, q: dict) -> bool:
    n = normalize(text)
    chosen = any(normalize(a) in n for a in q["answers"])
    rejected = any(normalize(r) in n for r in q.get("reject", []))
    reason = any(normalize(r) in n for r in q.get("reason_any", []))
    return chosen and not rejected and reason


def grade_answer(q: dict, text: str) -> bool:
    if not isinstance(text, str) or is_unknown(text):
        return False
    kind = q["match"]
    if kind == "contains":
        return match_contains(text, q["answers"])
    if kind == "sha":
        return match_sha(text, q["answers"])
    if kind == "number":
        return match_number(text, q["answers"])
    if kind == "verbatim":
        return match_verbatim(text, q["answers"])
    if kind == "label":
        return match_label(text, q["answers"], q["labels"])
    if kind == "fileline":
        return match_fileline(text, q["answers"])
    if kind == "decision":
        return match_decision(text, q)
    raise ValueError(f"unknown match kind {kind!r} for {q.get('id')}")


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_LINE = re.compile(r'^\s*"?([a-z]+\d+)"?\s*[:=]\s*"?(.*?)"?,?\s*$', re.MULTILINE)


def parse_answers(text: str, ids: list[str]) -> dict[str, str]:
    """Reader output -> {question_id: answer}. Tolerates a fenced block, a bare
    object, or `id: answer` lines. Missing ids map to ''."""
    cands = [m.group(1) for m in _JSON_BLOCK.finditer(text or "")][::-1]
    stripped = (text or "").strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        cands.append(stripped)
    for c in cands:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return {i: str(obj.get(i, "") if obj.get(i) is not None else "") for i in ids}
    found = {k: v for k, v in _LINE.findall(text or "")}
    return {i: found.get(i, "") for i in ids}


def _rate(num: int, denom: int):
    return (num / denom) if denom else None


def score_run(fixture: dict, answers: dict[str, str]) -> dict:
    rows = []
    for q in fixture["questions"]:
        ans = answers.get(q["id"], "")
        rows.append({"id": q["id"], "category": q["category"], "answer": ans,
                     "correct": grade_answer(q, ans)})
    out = {"n": len(rows), PRIMARY_METRIC: _rate(sum(r["correct"] for r in rows), len(rows))}
    for cat in CATEGORIES:
        sub = [r for r in rows if r["category"] == cat]
        out[f"recall_{cat}"] = _rate(sum(r["correct"] for r in sub), len(sub))
    out["rows"] = rows
    return out


def aggregate_runs(run_metrics: list[dict]) -> dict:
    out: dict = {"n_runs": len(run_metrics)}
    for k in METRIC_KEYS:
        vals = [m[k] for m in run_metrics if m.get(k) is not None]
        if vals:
            out[k] = {"mean": round(statistics.mean(vals), 4), "min": round(min(vals), 4),
                      "max": round(max(vals), 4),
                      "stdev": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0,
                      "n": len(vals), "values": [round(v, 4) for v in vals]}
        else:
            out[k] = None
    return out


def decide_verdict(with_agg: dict, baseline_agg: dict, min_delta: float = 0.05) -> dict:
    """keep / trim / BLOCKED ON MEASUREMENT on overall recall, CI-aware when the
    shared stats module is importable, else a plain delta threshold."""
    if stats is not None:
        stats.attach_ci(with_agg, baseline_agg, METRIC_KEYS)
        civ = stats.ci_verdict(with_agg, PRIMARY_METRIC, favorable="higher")
        if civ is not None:
            wm = (with_agg.get(PRIMARY_METRIC) or {}).get("mean")
            bm = (baseline_agg.get(PRIMARY_METRIC) or {}).get("mean")
            civ["delta_mean"] = round(wm - bm, 4) if wm is not None and bm is not None else None
            return civ
    wm = (with_agg.get(PRIMARY_METRIC) or {}).get("mean")
    bm = (baseline_agg.get(PRIMARY_METRIC) or {}).get("mean")
    if wm is None or bm is None:
        return {"verdict": "BLOCKED ON MEASUREMENT", "reason": "no recall values", "ci_aware": False}
    delta = round(wm - bm, 4)
    if delta > min_delta:
        return {"verdict": "keep", "reason": f"recall delta {delta} > {min_delta}", "delta_mean": delta,
                "ci_aware": False}
    if delta < -min_delta:
        return {"verdict": "trim", "reason": f"recall delta {delta} < -{min_delta}", "delta_mean": delta,
                "ci_aware": False}
    return {"verdict": "BLOCKED ON MEASUREMENT", "reason": f"recall delta {delta} within +-{min_delta}",
            "delta_mean": delta, "ci_aware": False}
