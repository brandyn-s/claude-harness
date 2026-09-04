#!/usr/bin/env python3
"""Pool several compaction A/B results files into one paired-bootstrap verdict.

run_live.py measures one fixture per results file (3 paired runs each). The
question "does the hook help across sessions, not just on one transcript?" is a
pooled question: every paired run is a (with_priorities - baseline) delta on the
same transcript under the same conditions, so deltas from different fixtures can
be pooled into one paired-bootstrap CI (skills/_shared/stats.py). Per-fixture CIs
are reported next to the pooled one so a fixture that carries the whole effect is
visible rather than averaged away.

Deterministic, key-free, no network: reads committed results files only.

  python3 skills/_shared/compaction-eval/combine_results.py \\
      skills/_shared/compaction-eval/results.json \\
      skills/_shared/compaction-eval/results-incident.json [--markdown]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))
import stats  # noqa: E402  (skills/_shared/stats.py)

ARMS = ("baseline", "with_priorities")
CATEGORIES = ("identifiers", "errors", "questions", "root_causes", "hypotheses", "decisions", "subagent")


def paired_recall(results: dict) -> tuple[list[float], list[float]]:
    """Per-run (with_priorities, baseline) overall recall, paired by run_idx; a run
    missing either arm is dropped from both lists."""
    by_run: dict[int, dict[str, float]] = {}
    for rec in results["records"]:
        by_run.setdefault(rec["run_idx"], {})[rec["arm"]] = rec["scores"]["recall"]
    complete = sorted(ri for ri, arms in by_run.items() if all(a in arms for a in ARMS))
    return ([by_run[ri]["with_priorities"] for ri in complete], [by_run[ri]["baseline"] for ri in complete])


def per_category_means(records: list[dict]) -> dict:
    out = {}
    for cat in CATEGORIES:
        out[cat] = {}
        for arm in ARMS:
            vals = [r["scores"].get(f"recall_{cat}") for r in records if r["arm"] == arm]
            vals = [v for v in vals if v is not None]
            out[cat][arm] = round(statistics.mean(vals), 4) if vals else None
    return out


def _verdict(ci: dict) -> str:
    if ci["direction"] == "positive":
        return "keep"
    if ci["direction"] == "negative":
        return "trim"
    return "BLOCKED ON MEASUREMENT"


def combine(results_list: list[tuple[str, dict]]) -> dict:
    per_fixture, with_all, base_all, records_all = [], [], [], []
    for name, results in results_list:
        w, b = paired_recall(results)
        if not w:
            raise ValueError(f"{name}: no complete paired runs")
        ci = stats.paired_bootstrap_ci(w, b)
        per_fixture.append({
            "file": name, "fixture": results.get("fixture", "coding"), "fixture_sha": results["fixture_sha"],
            "run_date": results.get("run_date"), "n_paired": len(w),
            "baseline": [round(x, 4) for x in b], "with_priorities": [round(x, 4) for x in w],
            "baseline_mean": round(statistics.mean(b), 4), "with_priorities_mean": round(statistics.mean(w), 4),
            "delta_mean": ci["delta_mean"], "ci95": [ci["ci_low"], ci["ci_high"]], "verdict": _verdict(ci),
            "recorded_verdict": (results.get("verdict") or {}).get("verdict"),
            "per_category": per_category_means(results["records"]),
            "cost_usd": (results.get("cost") or {}).get("actual_usd"),
        })
        with_all += w
        base_all += b
        records_all += results["records"]
    pooled_ci = stats.paired_bootstrap_ci(with_all, base_all)
    deltas = [w - b for w, b in zip(with_all, base_all)]
    return {
        "per_fixture": per_fixture,
        "pooled": {
            "n_paired": len(with_all), "fixtures": len(per_fixture),
            "baseline_mean": round(statistics.mean(base_all), 4),
            "with_priorities_mean": round(statistics.mean(with_all), 4),
            "deltas": [round(d, 4) for d in deltas], "delta_mean": pooled_ci["delta_mean"],
            "delta_min": round(min(deltas), 4), "ci95": [pooled_ci["ci_low"], pooled_ci["ci_high"]],
            "excludes_zero": pooled_ci["excludes_zero"], "verdict": _verdict(pooled_ci),
            "per_category": per_category_means(records_all),
            "runs_where_with_priorities_below_baseline": sum(1 for d in deltas if d < 0),
        },
    }


def render_markdown(combined: dict) -> str:
    p = combined["pooled"]
    lines = ["| fixture | n | baseline mean | with_priorities mean | delta mean | 95% CI | verdict |",
             "|---|---|---|---|---|---|---|"]
    for f in combined["per_fixture"]:
        lines.append(f"| {f['fixture']} (`{f['fixture_sha']}`) | {f['n_paired']} | {f['baseline_mean']:.3f} | "
                     f"{f['with_priorities_mean']:.3f} | {f['delta_mean']:+.4f} | [{f['ci95'][0]:.4f}, {f['ci95'][1]:.4f}] | "
                     f"{f['verdict']} |")
    lines.append(f"| **pooled** | {p['n_paired']} | {p['baseline_mean']:.3f} | {p['with_priorities_mean']:.3f} | "
                 f"{p['delta_mean']:+.4f} | [{p['ci95'][0]:.4f}, {p['ci95'][1]:.4f}] | **{p['verdict']}** |")
    lines += ["", "| category | " + " | ".join(f"{f['fixture']} baseline | {f['fixture']} with" for f in combined["per_fixture"])
              + " | pooled baseline | pooled with |",
              "|---|" + "---|---|" * (len(combined["per_fixture"]) + 1)]
    for cat in CATEGORIES:
        cells = []
        for f in combined["per_fixture"]:
            cells += [_fmt(f["per_category"][cat]["baseline"]), _fmt(f["per_category"][cat]["with_priorities"])]
        cells += [_fmt(p["per_category"][cat]["baseline"]), _fmt(p["per_category"][cat]["with_priorities"])]
        lines.append(f"| {cat} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _fmt(v) -> str:
    return "n/a" if v is None else f"{v:.3f}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("results", nargs="+", type=Path)
    ap.add_argument("--markdown", action="store_true", help="print RESULTS.md tables instead of JSON")
    args = ap.parse_args(argv)
    loaded = [(p.name, json.loads(p.read_text(encoding="utf-8"))) for p in args.results]
    combined = combine(loaded)
    if args.markdown:
        print(render_markdown(combined))
    else:
        print(json.dumps(combined, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
