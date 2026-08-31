#!/usr/bin/env python3
"""Pure, key-free scorer for the triage live-arm efficacy harness.

See harness/PROBLEM.md. triage's value-prop is correct PRIORITIZATION + cross-tool
CORRELATION, so this grader measures (a) Spearman rank correlation between the arm's
ranking and the expert ranking, and (b) pair-level precision/recall/F1 of the arm's
proposed correlation groups vs the known root-cause groups. NO network/API calls; no
scipy (Spearman hand-rolled).

Anti-circularity: the expert ranking + groups are human-curated ground truth; the
producer never sets them.
"""
from __future__ import annotations

import math
import statistics
import sys
from itertools import combinations
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
_CI_PRIMARY_METRIC = "spearman"


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    vy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if vx == 0 or vy == 0:
        return 0.0
    return cov / (vx * vy)


def spearman(arm_order: list[str], fixture: dict) -> float:
    """Spearman = Pearson on ranks. arm_order is the arm's ranking best->worst.
    Any fixture id the arm omitted is assigned the worst rank (tie-shared)."""
    ids = [f["id"] for f in fixture["findings"]]
    n = len(ids)
    expert = {f["id"]: f["expert_rank"] for f in fixture["findings"]}
    # arm rank: position in arm_order (1-based); omitted ids share the worst average rank
    arm_rank = {}
    pos = 1
    seen = []
    for x in arm_order:
        if x in expert and x not in arm_rank:
            arm_rank[x] = pos
            seen.append(x)
            pos += 1
    missing = [i for i in ids if i not in arm_rank]
    if missing:
        worst_avg = (pos + n) / 2.0  # average of the remaining ranks
        for i in missing:
            arm_rank[i] = worst_avg
    xs = [arm_rank[i] for i in ids]
    ys = [expert[i] for i in ids]
    return round(_pearson(xs, ys), 4)


def _pairs(groups):
    out = set()
    for g in groups:
        for a, b in combinations(sorted(set(g)), 2):
            out.add((a, b))
    return out


def group_prf(arm_groups, true_groups):
    ap, tp = _pairs(arm_groups), _pairs(true_groups)
    if not ap and not tp:
        return 1.0, 1.0, 1.0
    inter = len(ap & tp)
    precision = (inter / len(ap)) if ap else (1.0 if not tp else 0.0)
    recall = (inter / len(tp)) if tp else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return round(precision, 4), round(recall, 4), round(f1, 4)


def score_run(fixture: dict, record: dict) -> dict:
    """record = {ranking: [ids best->worst], groups: [[ids], ...]}."""
    sp = spearman(record.get("ranking", []), fixture)
    p, r, f1 = group_prf(record.get("groups", []), fixture["true_groups"])
    return {"spearman": sp, "group_precision": p, "group_recall": r, "group_f1": f1,
            "n_ranked": len({x for x in record.get("ranking", []) if x})}


_METRIC_KEYS = ("spearman", "group_precision", "group_recall", "group_f1")


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
    """keep / trim / fix on triage's value-prop (better ranking + correlation).

    Primary = spearman (ranking quality); secondary = group_f1 (correlation detection).
      keep : harness spearman beats baseline beyond noise AND group_f1 not worse, OR
             group_f1 beats baseline beyond noise AND spearman not worse.
      fix  : harness is meaningfully WORSE than baseline on spearman or group_f1.
      trim : both within noise — the 14-article ceremony isn't buying better triage.
    """
    def m(d, k):
        return (d.get(k) or {}).get("mean")

    def std(d, k):
        return (d.get(k) or {}).get("stdev", 0.0) or 0.0

    sp_w, sp_b = m(with_skill, "spearman"), m(baseline, "spearman")
    f1_w, f1_b = m(with_skill, "group_f1"), m(baseline, "group_f1")
    if sp_w is None or sp_b is None:
        return {"verdict": "inconclusive", "reason": "missing spearman"}
    sp_noise = max(min_delta, std(with_skill, "spearman"))
    f1_noise = max(min_delta, std(with_skill, "group_f1"))
    sp_d, f1_d = round(sp_w - sp_b, 4), round((f1_w or 0) - (f1_b or 0), 4)

    if sp_w + sp_noise < sp_b or (f1_w is not None and f1_b is not None and f1_w + f1_noise < f1_b):
        return {"verdict": "fix", "reason": f"harness WORSE than baseline (spearman {sp_w} vs {sp_b}, "
                f"group_f1 {f1_w} vs {f1_b}) — the framework degrades triage", "spearman_delta": sp_d}

    # CI-aware rule (Phase B): the legacy `fix` check above (clear degradation on
    # spearman/group_f1) still takes precedence. Past it, when paired per-run CI is
    # available on spearman, the CI verdict GOVERNS the keep/trim/BLOCKED decision.
    # Legacy noise-threshold below is the fallback when no CI.
    if stats is not None:
        civ = stats.ci_verdict(with_skill, _CI_PRIMARY_METRIC, favorable="higher")
        if civ is not None:
            civ.update({"spearman_delta": sp_d, "group_f1_delta": f1_d,
                        "legacy_min_delta": min_delta})
            return civ

    if sp_d > sp_noise or (f1_d > f1_noise):
        return {"verdict": "keep", "reason": f"harness improves triage (spearman {sp_w} vs {sp_b} "
                f"delta {sp_d}; group_f1 {f1_w} vs {f1_b} delta {f1_d}) beyond noise",
                "spearman_delta": sp_d, "group_f1_delta": f1_d}
    return {"verdict": "trim", "reason": f"spearman delta {sp_d} + group_f1 delta {f1_d} within noise "
            f"— 14-article framework not buying materially better ranking/correlation",
            "spearman_delta": sp_d, "group_f1_delta": f1_d}
